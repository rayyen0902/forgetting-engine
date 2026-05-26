"""ForgettingEngine: the core forgetting-middleware engine.

Multi-agent: each agent = isolated M-Clock + traces + domain.
"""

import json
from datetime import timedelta

from forgetting_engine.domain_adapter import DefaultAdapter, DomainAdapter
from forgetting_engine.embedding import EmbeddingProvider, StubEmbeddingProvider
from forgetting_engine.llm import LLMProvider, StubLLMProvider
from forgetting_engine.logger import EngineLog, EngineLogger
from forgetting_engine.models import (
    Cue,
    DecayCurve,
    DecayReport,
    EngineContext,
    L0_RawMessage,
    L1_Episode,
    L2_Pattern,
    L3_Fact,
    Layer,
    MemoryTrace,
    RetainCondition,
    RetrievalContext,
)
from forgetting_engine.time_position import TimePosition
from forgetting_engine.utils import (
    _extract_text,
    _text_contains_any,
    cosine_sim,
    generate_id,
    mean_vals,
    now,
)


def _is_constraint_fact(trace: MemoryTrace) -> bool:
    """Check if a trace holds a constraint-type L3 fact (permanently retained)."""
    return (
        isinstance(trace.content, L3_Fact)
        and trace.content.fact_type == "constraint"
    )


class AgentRuntime:
    """Per-agent isolated state."""

    def __init__(
        self,
        agent_id: str,
        domain_name: str,
        domain: DomainAdapter,
    ):
        self.agent_id = agent_id
        self.domain_name = domain_name
        self.domain = domain
        self.clock = TimePosition()
        self.traces: dict[str, MemoryTrace] = {}
        self.retain_conditions: list[RetainCondition] = []
        self.wall_clock_start = now()
        self.created_at = now()
        self.is_active = True


class ForgettingEngine:
    """General-purpose forgetting engine — multi-agent shared instance.

    agent_id is the top isolation key:
      - Independent M-Clock per agent
      - Independent traces + retain_conditions per agent
      - Each agent bound to one domain (set at creation, immutable)
    """

    _domain_registry: dict[str, type[DomainAdapter]] = {
        "default": DefaultAdapter,
    }

    @classmethod
    def register_domain(cls, name: str, adapter_cls: type[DomainAdapter]) -> None:
        """Register a domain adapter class (call once at engine startup)."""
        cls._domain_registry[name] = adapter_cls

    def __init__(
        self,
        embedding_provider: EmbeddingProvider | None = None,
        llm_provider: LLMProvider | None = None,
    ):
        self.agents: dict[str, AgentRuntime] = {}
        self.logger = EngineLogger()
        self._embedding = embedding_provider or StubEmbeddingProvider()
        self._llm = llm_provider or StubLLMProvider()

    # ── Provider helpers ──────────────────────────────────

    def _embed(self, text: str) -> list[float]:
        return self._embedding.embed(text)

    def _safe_llm_json(self, prompt: str) -> dict:
        """Call LLM and safely parse JSON response.

        Handles: dict, JSON string, markdown-wrapped JSON, plain text.
        """
        result = self._llm.call(prompt)
        if isinstance(result, dict):
            return result
        if isinstance(result, str):
            text = result.strip()
            # Strip markdown code fences
            if text.startswith("```"):
                lines = text.split("\n")
                # Remove first line (```json or ```) and last line (```)
                text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                # Plain text fallback: wrap as description
                return {"description": text}
        return {}

    # ── Agent lifecycle ───────────────────────────────────

    def create_agent(self, agent_id: str, domain_name: str = "default") -> str:
        """Create an agent. Returns agent_id.

        One agent = one independent memory space (M-Clock + traces + domain).
        Switching domain = create a new agent.
        """
        if agent_id in self.agents:
            raise ValueError(f"Agent '{agent_id}' already exists")

        adapter_cls = self._domain_registry.get(domain_name)
        if adapter_cls is None:
            raise ValueError(f"Unknown domain: '{domain_name}'")

        domain = adapter_cls()
        rt = AgentRuntime(agent_id=agent_id, domain_name=domain_name, domain=domain)
        self._init_retain_conditions(rt)
        self.agents[agent_id] = rt

        self._log(
            agent_id,
            "agent",
            [agent_id],
            f"Agent created: domain={domain_name}",
            {"domain": domain_name},
            "created",
        )
        return agent_id

    def delete_agent(self, agent_id: str) -> None:
        """Soft-delete an agent (mark inactive, GC cleans up traces later)."""
        if agent_id not in self.agents:
            return
        self.agents[agent_id].is_active = False
        self._log(agent_id, "agent", [agent_id], "Agent deactivated", decision="deactivated")

    def list_agents(self) -> list[dict]:
        """List all agents."""
        return [
            {
                "agent_id": r.agent_id,
                "domain": r.domain_name,
                "clock": str(r.clock),
                "trace_count": len(r.traces),
                "is_active": r.is_active,
            }
            for r in self.agents.values()
        ]

    # ── Internal routing ──────────────────────────────────

    def _rt(self, agent_id: str) -> AgentRuntime:
        """Get agent runtime (error if not found)."""
        if agent_id not in self.agents:
            raise ValueError(f"Agent '{agent_id}' not found. Call create_agent() first.")
        rt = self.agents[agent_id]
        if not rt.is_active:
            raise ValueError(f"Agent '{agent_id}' is deactivated.")
        return rt

    def _log(
        self,
        agent_id: str,
        operation: str,
        trace_ids: list[str],
        detail: str,
        metrics: dict | None = None,
        decision: str = "",
    ) -> None:
        """Append an operation log entry tagged with agent_id."""
        rt = self.agents.get(agent_id)
        clock = rt.clock if rt else TimePosition()
        self.logger.append(
            EngineLog(
                id=generate_id(),
                time=clock,
                wall_clock=now(),
                operation=operation,
                trace_ids=trace_ids,
                detail=f"[{agent_id}] {detail}",
                metrics=metrics or {},
                decision=decision,
            )
        )

    # ── Clock ─────────────────────────────────────────────

    def _tick(self, agent_id: str) -> TimePosition:
        """Advance agent clock by 1m."""
        rt = self._rt(agent_id)
        rt.clock = rt.clock.add_m(1)
        return rt.clock

    # ── Ingest ────────────────────────────────────────────

    def ingest(self, agent_id: str, message: L0_RawMessage) -> str:
        """Data enters the engine. Advances agent M-Clock by 1m."""
        rt = self._rt(agent_id)
        current = self._tick(agent_id)

        trace = MemoryTrace(
            id=generate_id(),
            layer=Layer.L0,
            content=message,
            born_at=current,
            wall_clock_born=now(),
            decay_curve=DecayCurve(
                initial=1.0,
                lambda_=self._base_lambda(),
                last_access=current,
                access_count=0,
            ),
            connectivity_score=0,
            significance=0.0,
            retained_by=[],
            immunity_until=None,
            parent_trace_ids=[],
            child_trace_ids=[],
            is_first_of_session=False,
            deleted_at=None,
        )

        trace.connectivity_score = self._compute_connectivity(rt, trace)
        trace.decay_curve.lambda_ = self._adjusted_lambda(trace.connectivity_score)

        rt.traces[trace.id] = trace
        self._log(
            agent_id,
            "ingest",
            [trace.id],
            f"L0 ingested: session={message.session_id}",
            {"connectivity": trace.connectivity_score, "lambda": trace.decay_curve.lambda_},
        )
        self._maybe_trigger_capacity_check(rt, Layer.L0)

        return trace.id

    def ingest_significant(
        self, agent_id: str, message: L0_RawMessage, significance: float
    ) -> str:
        """Ingest with significance marking. Triggers backtrace enhancement window.

        Backtrace window: 1 scene + 2 moments = 10m.
        Related traces within the window get cascading significance.
        """
        rt = self._rt(agent_id)
        BACKTRACE_WINDOW = TimePosition.M_PER_S + 2
        current = rt.clock
        trace_id = self.ingest(agent_id, message)
        trace = rt.traces[trace_id]
        trace.significance = significance

        window_start = current.add_m(-BACKTRACE_WINDOW)
        for t in rt.traces.values():
            if t.is_deleted():
                continue
            if t.born_at < window_start:
                continue
            sim = rt.domain.similarity(
                self._to_content_for_comparison(t),
                self._to_content_for_comparison(trace),
            )
            if sim > 0.5:
                burst = significance * 0.8
                if burst > t.significance:
                    t.significance = burst
        return trace_id

    # ── Decay cycle ───────────────────────────────────────

    def decay_cycle(self, agent_id: str | None = None) -> dict[str, DecayReport]:
        """Main forgetting cycle.

        agent_id=None → iterate all agents
        agent_id=str  → only process that agent

        L0→L1 and L1→L2 use batch compression: all traces in the same layer
        that fall below threshold are compressed together.
        L2→L3 and L3→L4 use per-trace compression.
        """
        reports: dict[str, DecayReport] = {}
        targets = [agent_id] if agent_id else list(self.agents.keys())

        for aid in targets:
            rt = self.agents.get(aid)
            if rt is None or not rt.is_active:
                continue
            report = DecayReport()
            current = rt.clock

            for layer in [Layer.L0, Layer.L1, Layer.L2, Layer.L3]:
                traces_in_layer = [
                    t
                    for t in rt.traces.values()
                    if t.layer == layer and not t.is_deleted()
                    and not _is_constraint_fact(t)
                ]
                traces_in_layer.sort(key=lambda t: t.retention(current))

                to_descend: list[MemoryTrace] = []

                for trace in traces_in_layer:
                    if (
                        trace.immunity_until is not None
                        and current < trace.immunity_until
                    ):
                        continue

                    hit = self._check_retain_conditions(rt, trace)
                    if hit:
                        trace.retained_by = [hit.name]
                        trace.decay_curve = DecayCurve(
                            initial=1.0,
                            lambda_=trace.decay_curve.lambda_,
                            last_access=current,
                            access_count=trace.decay_curve.access_count,
                        )
                        trace.immunity_until = current.add_m(hit.immunity_m)
                        self._log(
                            aid,
                            "decay",
                            [trace.id],
                            f"L{trace.layer.value} retained by '{hit.name}'",
                            {
                                "retention": trace.retention(current),
                                "immunity_m": hit.immunity_m,
                            },
                            "retained",
                        )
                        report.retained += 1
                        continue

                    r = trace.retention(current)
                    threshold = self._threshold_for_descend(layer)
                    if r < threshold:
                        to_descend.append(trace)

                if not to_descend:
                    continue

                if layer in (Layer.L0, Layer.L1):
                    # Batch compress: all traces in this layer → one or more children
                    self._batch_descend(rt, to_descend, layer)
                    self._log(
                        aid,
                        "decay",
                        [t.id for t in to_descend],
                        f"L{layer.value}→L{layer.value + 1} batch-descended ({len(to_descend)} traces)",
                        {"count": len(to_descend)},
                        "descended",
                    )
                    report.descended[layer] += len(to_descend)
                else:
                    # Per-trace: L2→L3, L3→L4
                    for trace in to_descend:
                        r = trace.retention(current)
                        self._descend(rt, trace)
                        self._log(
                            aid,
                            "decay",
                            [trace.id],
                            f"L{layer.value}→L{layer.value + 1} descended",
                            {"retention": r, "threshold": threshold},
                            "descended",
                        )
                        report.descended[layer] += 1

                        if trace.layer == Layer.L4:
                            self._soft_delete(rt, trace)
                            self._log(
                                aid,
                                "decay",
                                [trace.id],
                                "L4 soft-deleted",
                                {"retention": r},
                                "deleted",
                            )
                            report.deleted += 1

            reports[aid] = report

        return reports

    # ── Descend (layer compression) ───────────────────────

    def _descend(self, rt: AgentRuntime, trace: MemoryTrace) -> None:
        """Per-trace descend for L2→L3 and L3→L4.

        L0→L1 and L1→L2 are handled by _batch_descend in decay_cycle.
        """
        old_layer = trace.layer
        new_layer = Layer(old_layer.value + 1)
        current = rt.clock
        new_content: object = None

        if old_layer == Layer.L2:
            facts = self._compress_L2_to_L3(rt, [trace.content])
            # facts is list[L3_Fact] — create one child per fact
            for fact in facts:
                child = self._create_child_trace(
                    rt, fact, new_layer,
                    parent_ids=[trace.id],
                    significance=trace.significance * 0.8,
                )
                trace.child_trace_ids.append(child.id)
                rt.traces[child.id] = child
                self._log(
                    rt.agent_id,
                    "descend",
                    [trace.id, child.id],
                    f"L{old_layer.value}→L{new_layer.value}",
                    {"from_layer": old_layer.value, "to_layer": new_layer.value},
                )
            self._soft_delete(rt, trace)
            return  # Soft-deleted; skip trace.layer = new_layer below

        elif old_layer == Layer.L3:
            # L3→L4: no compression, just transition to deleted state
            new_content = None

        trace.layer = new_layer

        if new_content is not None:
            child = self._create_child_trace(
                rt, new_content, new_layer,
                parent_ids=[trace.id],
                significance=trace.significance * 0.8,
            )
            trace.child_trace_ids.append(child.id)
            rt.traces[child.id] = child
            self._log(
                rt.agent_id,
                "descend",
                [trace.id, child.id],
                f"L{old_layer.value}→L{new_layer.value}",
                {"from_layer": old_layer.value, "to_layer": new_layer.value},
            )

    def _batch_descend(
        self, rt: AgentRuntime, traces: list[MemoryTrace], from_layer: Layer
    ) -> None:
        """Batch compress multiple traces from the same layer.

        L0→L1: all messages → one L1_Episode
        L1→L2: all episodes → multiple L2_Patterns (via clustering)
        """
        current = rt.clock
        to_layer = Layer(from_layer.value + 1)
        parent_ids = [t.id for t in traces]
        max_sig = max((t.significance for t in traces), default=0.0)

        if from_layer == Layer.L0:
            messages = [t.content for t in traces if isinstance(t.content, L0_RawMessage)]
            if messages:
                episode = self._compress_L0_to_L1(rt, messages)
                child = self._create_child_trace(
                    rt, episode, to_layer,
                    parent_ids=parent_ids,
                    significance=max_sig * 0.8,
                )
                rt.traces[child.id] = child
                for t in traces:
                    t.child_trace_ids.append(child.id)
                self._log(
                    rt.agent_id, "descend",
                    parent_ids + [child.id],
                    f"L0→L1 batch: {len(messages)} msgs → 1 episode",
                    {"msg_count": len(messages)},
                )
            for t in traces:
                self._soft_delete(rt, t)

        elif from_layer == Layer.L1:
            episodes = [t.content for t in traces if isinstance(t.content, L1_Episode)]
            child_ids: list[str] = []
            if episodes:
                patterns = self._compress_L1_to_L2(rt, episodes)
                for pattern in patterns:
                    child = self._create_child_trace(
                        rt, pattern, to_layer,
                        parent_ids=parent_ids,
                        significance=max_sig * 0.8,
                    )
                    rt.traces[child.id] = child
                    child_ids.append(child.id)
                for t in traces:
                    t.child_trace_ids.extend(child_ids)
                self._log(
                    rt.agent_id, "descend",
                    parent_ids + child_ids,
                    f"L1→L2 batch: {len(episodes)} episodes → {len(patterns)} patterns",
                    {"episode_count": len(episodes), "pattern_count": len(patterns)},
                )
            for t in traces:
                self._soft_delete(rt, t)

    def _create_child_trace(
        self,
        rt: AgentRuntime,
        content: object,
        layer: Layer,
        parent_ids: list[str],
        significance: float,
    ) -> MemoryTrace:
        current = rt.clock
        return MemoryTrace(
            id=generate_id(),
            layer=layer,
            content=content,
            born_at=current,
            wall_clock_born=now(),
            decay_curve=DecayCurve(
                initial=1.0,
                lambda_=self._base_lambda(),
                last_access=current,
                access_count=0,
            ),
            connectivity_score=self._compute_connectivity_for(rt, content),
            significance=significance,
            retained_by=[],
            immunity_until=None,
            parent_trace_ids=list(parent_ids),
            child_trace_ids=[],
            is_first_of_session=False,
            deleted_at=None,
        )

    # ── Compression algorithms ─────────────────────────────

    def _compress_L0_to_L1(
        self, rt: AgentRuntime, messages: list[L0_RawMessage]
    ) -> L1_Episode:
        """Batch L0→L1: compress multiple raw messages into one narrative episode."""
        dialogue = "\n".join(f"[{m.role}] {m.text}" for m in messages)
        prompt = (
            "将以下对话片段压缩为一条叙事记录，填入固定字段。\n"
            f"action_type 从以下选择：{rt.domain.action_types()}\n\n"
            f"对话：\n{dialogue}\n\n"
            "返回 JSON：\n"
            '{\n'
            '    "topic": "语义主题",\n'
            '    "action_type": "...",\n'
            '    "subject_entity": "核心实体",\n'
            '    "predicate": "做了什么/发生了什么",\n'
            '    "outcome": "结果/结论",\n'
            '    "negation": "明确否定了什么（无则null）",\n'
            '    "emotional_tone": -1.0到1.0\n'
            "}"
        )
        result = self._safe_llm_json(prompt)
        emb = self._embedding
        participants = list({m.role for m in messages})
        return L1_Episode(
            participants=participants,
            topic=result.get("topic", ""),
            action_type=result.get("action_type", "general"),
            subject_entity=result.get("subject_entity", ""),
            predicate=result.get("predicate", ""),
            outcome=result.get("outcome", ""),
            negation=result.get("negation"),
            emotional_tone=float(result.get("emotional_tone", 0.0)),
            time=rt.clock,
            wall_clock=now(),
            embedding=emb.embed(
                result.get("topic", "") + " " + result.get("predicate", "")
            ),
        )

    def _compress_L1_to_L2(
        self, rt: AgentRuntime, episodes: list[L1_Episode]
    ) -> list[L2_Pattern]:
        """Batch L1→L2: cluster episodes into behavioral patterns.

        Three induction strategies:
          1. frequency — episodes clustered by similarity (habits)
          2. contrast — same entity, different outcomes (preferences)
          3. cascade — outcome→entity chains (causal patterns)
        """
        current = rt.clock
        patterns: list[L2_Pattern] = []

        # Strategy 1: Frequency — similar episodes → habit patterns
        clusters = self._cluster_by_similarity(
            episodes,
            similarity_fn=lambda a, b: rt.domain.similarity(a, b),
            threshold=0.6,
        )
        for cluster in clusters:
            if len(cluster) >= 2:
                patterns.append(L2_Pattern(
                    type="frequency",
                    description=self._summarize_frequency_pattern(cluster),
                    confidence=min(len(cluster) / 5.0, 1.0),
                    source_episode_ids=[],
                    evidence_count=len(cluster),
                    last_observed_at=current,
                ))

        # Strategy 2: Contrast — same entity, different outcomes → preferences
        for entity, eps in self._group_by_entity(episodes).items():
            if len(eps) >= 2 and len({e.outcome for e in eps}) >= 2:
                patterns.append(L2_Pattern(
                    type="contrast",
                    description=self._summarize_contrast_pattern(eps),
                    confidence=0.7,
                    source_episode_ids=[],
                    evidence_count=len(eps),
                    last_observed_at=current,
                ))

        # Strategy 3: Cascade — outcome→entity chains → causal patterns
        chains = self._find_causal_chains(episodes, max_depth=4)
        for chain in chains:
            patterns.append(L2_Pattern(
                type="cascade",
                description=self._describe_chain(chain),
                confidence=0.85,
                source_episode_ids=[],
                evidence_count=1,
                last_observed_at=current,
            ))

        return patterns

    def _compress_L2_to_L3(self, rt: AgentRuntime, patterns: list[L2_Pattern]) -> list[L3_Fact]:
        facts: list[L3_Fact] = []
        schema = rt.domain.fact_schema()
        current = rt.clock

        for pattern in patterns:
            if pattern.type == "frequency" and pattern.confidence >= 0.8:
                key, value, sentence = self._pattern_to_fact_kv(pattern, schema)
                if key and sentence:
                    facts.append(
                        L3_Fact(
                            key=key,
                            value=value,
                            fact_type="identity",
                            sentence=sentence,
                            confidence=pattern.confidence,
                            source_pattern_ids=[],
                            last_updated_at=current,
                        )
                    )

            if pattern.type == "contrast":
                key, value, sentence = self._contrast_to_preference(pattern, schema)
                if key and sentence:
                    facts.append(
                        L3_Fact(
                            key=key,
                            value=value,
                            fact_type="preference",
                            sentence=sentence,
                            confidence=pattern.confidence,
                            source_pattern_ids=[],
                            last_updated_at=current,
                        )
                    )

            if self._matches_danger_signal(rt, pattern.description):
                key, value, sentence = self._pattern_to_fact_kv(pattern, schema)
                if key and sentence:
                    facts.append(
                        L3_Fact(
                            key=key,
                            value=value,
                            fact_type="constraint",
                            sentence=sentence,
                            confidence=max(pattern.confidence, 0.5),
                            source_pattern_ids=[],
                            last_updated_at=current,
                        )
                    )

        return facts

    # ── Retrieve ──────────────────────────────────────────

    def retrieve(
        self, agent_id: str, context: RetrievalContext
    ) -> list[MemoryTrace]:
        """Agent memory retrieval.
        Active injection (L0+L1) + passive wake-up (L2+L3).
        """
        rt = self._rt(agent_id)
        results: list[tuple[MemoryTrace, float, str]] = []
        current = rt.clock
        context.current_m = current.to_m()  # For domain adapter time-weighted relevance

        # Active traces (always injected)
        for trace in self._active_traces(rt):
            if trace.is_deleted():
                continue
            relevance = rt.domain.relevance(trace, context)
            if relevance > 0.0:
                trace.decay_curve.access_count += 1
                trace.decay_curve.last_access = current
                results.append((trace, relevance, "active"))

        # Latent traces (must be activated by cues)
        for trace in self._latent_traces(rt):
            if trace.is_deleted():
                continue
            activation = 0.0
            for cue in context.cues:
                activation += self._cue_activation(rt, trace, cue)

            if activation >= rt.domain.activation_threshold(trace.layer):
                trace.decay_curve.access_count += 1
                trace.decay_curve.last_access = current
                results.append((trace, activation, "latent"))

        active_count = sum(1 for _, _, path in results if path == "active")
        latent_count = len(results) - active_count
        self._log(
            agent_id,
            "retrieve",
            [r[0].id for r in results],
            f"Retrieved {len(results)} traces",
            {
                "active": active_count,
                "latent": latent_count,
                "cues": [c.value for c in context.cues],
            },
        )

        results.sort(key=lambda x: (0 if x[2] == "active" else 1, -x[1]))
        return [r[0] for r in results]

    # ── Render for injection ──────────────────────────────

    def render_for_injection(
        self,
        agent_id: str,
        traces: list[MemoryTrace],
        context: RetrievalContext,
    ) -> str:
        """Render retrieved traces as LLM injection text.

        Structure: [Current dialogue] / [Background] / [Attention]
        """
        rt = self._rt(agent_id)
        current_session = context.current_session_id

        l0_current: list[L0_RawMessage] = []
        l1_other: list[MemoryTrace] = []
        l3_facts: list[MemoryTrace] = []

        for t in traces:
            if t.layer == Layer.L0:
                msg = t.content
                if isinstance(msg, L0_RawMessage) and msg.session_id == current_session:
                    l0_current.append(msg)
            elif t.layer == Layer.L1:
                l1_other.append(t)
            elif t.layer == Layer.L3:
                l3_facts.append(t)

        blocks: list[str] = []

        if l0_current:
            blocks.append(f"[当前对话]\n{self._render_dialogue(l0_current)}")

        background_lines: list[str] = []

        for t in l3_facts:
            fact = t.content
            if isinstance(fact, L3_Fact):
                background_lines.append(
                    f"{self._layer_tag(t, rt.clock)} {fact.sentence}"
                )

        if l1_other:
            stitched = self._stitch_L1_episodes(agent_id, l1_other)
            if stitched:
                background_lines.append(stitched)

        if background_lines:
            blocks.append("[背景]\n" + "\n".join(background_lines))

        conflicts = self._detect_conflicts(l3_facts, l0_current)
        if conflicts:
            blocks.append("[注意]\n" + "\n".join(conflicts))

        result = "\n\n".join(blocks)
        self._log(
            agent_id,
            "inject",
            [t.id for t in traces],
            f"Injection rendered: {len(l0_current)} L0, {len(l1_other)} L1, {len(l3_facts)} L3",
            {
                "l0_count": len(l0_current),
                "l1_count": len(l1_other),
                "l3_count": len(l3_facts),
                "conflicts": len(conflicts),
            },
        )
        return result

    def _render_dialogue(self, messages: list[L0_RawMessage]) -> str:
        return "\n".join(f"[{msg.role}] {msg.text}" for msg in messages)

    def _stitch_L1_episodes(
        self, agent_id: str, traces: list[MemoryTrace]
    ) -> str:
        rt = self._rt(agent_id)
        items: list[str] = []
        for t in traces:
            ep = t.content
            if isinstance(ep, L1_Episode):
                tone_label = self._tone_label(ep.emotional_tone)
                items.append(
                    f"[{self._layer_tag(t, rt.clock)}] {ep.predicate}，{ep.outcome} [{tone_label}]"
                )

        if not items:
            return ""

        prompt = (
            "将以下关于用户的记忆片段整合为2-3句连贯的背景描述。"
            "保留关键信息，去掉重复。不要添加不存在的信息。"
            "情绪标签仅作为语境的提示，不需要在输出中提及。\n\n"
            + "\n".join(items)
            + '\n\n返回 JSON: {"description": "整合后的文本"}'
        )
        result = self._safe_llm_json(prompt)
        stitched = result.get("description", "")
        self._log(
            agent_id,
            "inject",
            [t.id for t in traces],
            f"L1 stitched: {len(traces)} episodes → 1 paragraph",
            {"episode_count": len(traces)},
            "stitched",
        )
        return stitched

    def _detect_conflicts(
        self, l3_facts: list[MemoryTrace], l0_messages: list[L0_RawMessage]
    ) -> list[str]:
        conflicts: list[str] = []
        l0_text = " ".join(m.text for m in l0_messages)
        if not l0_text:
            return conflicts

        for t in l3_facts:
            fact = t.content
            if not isinstance(fact, L3_Fact):
                continue
            prompt = (
                "判断以下两段信息是否存在矛盾。仅在有明确矛盾时返回 true。\n"
                f"已知事实: {fact.sentence}\n"
                f"当前用户消息: {l0_text}\n"
                '返回 JSON: {"conflict": true|false, "detail": "矛盾描述或空"}'
            )
            result = self._safe_llm_json(prompt)
            if result.get("conflict"):
                detail = result.get("detail", "")
                conflicts.append(
                    f"检测到矛盾——L3 记录为「{fact.sentence}」，"
                    f"但当前对话中用户反馈「{detail}」。"
                    "请综合判断，可能是短期波动或 L3 记录已过时。"
                )

        return conflicts

    def _layer_tag(self, trace: MemoryTrace, now: TimePosition) -> str:
        """Layer tag + M-Clock relative offset."""
        dist = now.distance_m(trace.born_at)
        M = TimePosition

        if dist >= M.M_PER_E:
            return f"[L{trace.layer.value} -{dist // M.M_PER_E}e]"
        elif dist >= M.M_PER_V:
            return f"[L{trace.layer.value} -{dist // M.M_PER_V}v]"
        elif dist >= M.M_PER_C:
            c = dist // M.M_PER_C
            s_rem = (dist % M.M_PER_C) // M.M_PER_S
            suffix = f"-{c}c{s_rem}s" if s_rem else f"-{c}c"
            return f"[L{trace.layer.value} {suffix}]"
        elif dist >= M.M_PER_S:
            s = dist // M.M_PER_S
            m_rem = dist % M.M_PER_S
            suffix = f"-{s}s{m_rem}m" if m_rem else f"-{s}s"
            return f"[L{trace.layer.value} {suffix}]"
        else:
            return f"[L{trace.layer.value} -{dist}m]"

    @staticmethod
    def _tone_label(tone: float) -> str:
        if tone >= 0.5:
            return "积极"
        elif tone >= 0.1:
            return "中性偏积极"
        elif tone >= -0.1:
            return "中性"
        elif tone >= -0.5:
            return "略消极"
        else:
            return "消极"

    def _cue_activation(
        self, rt: AgentRuntime, trace: MemoryTrace, cue: Cue
    ) -> float:
        base = rt.domain.relevance(trace, cue)
        if trace.layer == Layer.L2:
            return base
        elif trace.layer == Layer.L3:
            return base * 0.6
        return base

    # ── Retain conditions ─────────────────────────────────

    def _init_retain_conditions(self, rt: AgentRuntime) -> None:
        engine = self  # noqa: F841  # Capture for closures
        M = TimePosition
        rt.retain_conditions = [
            RetainCondition(
                name="显式记忆指令",
                priority=100,
                evaluate=lambda t, ctx: _text_contains_any(
                    t.content, ["记住", "别忘了", "记下来", "remember"]
                ),
                immunity_m=M.M_PER_V,
            ),
            RetainCondition(
                name="高频提取",
                priority=80,
                evaluate=lambda t, ctx: (
                    t.decay_curve.access_count >= 3
                    and ctx.now.distance_m(t.decay_curve.last_access) <= M.M_PER_C
                ),
                immunity_m=M.M_PER_C,
            ),
            RetainCondition(
                name="关联锚定",
                priority=60,
                evaluate=lambda t, ctx: t.connectivity_score >= 3,
                immunity_m=M.M_PER_C * 3,
            ),
            RetainCondition(
                name="首因/近因效应",
                priority=40,
                evaluate=lambda t, ctx: (
                    t.is_first_of_session
                    or ctx.now.distance_m(t.born_at) <= M.M_PER_S * 2
                ),
                immunity_m=M.M_PER_S * 2,
            ),
            RetainCondition(
                name="矛盾标记",
                priority=90,
                evaluate=lambda t, ctx: self._has_conflict_with_newer(t, rt),
                immunity_m=M.M_PER_C * 2,
            ),
            RetainCondition(
                name="领域危险信号",
                priority=95,
                evaluate=lambda t, ctx: rt.domain.is_danger_signal(
                    _extract_text(t.content)
                ),
                immunity_m=M.M_PER_E,
            ),
        ]
        # Register domain-extra conditions
        for cond in rt.domain.extra_retain_conditions():
            rt.retain_conditions.append(cond)

    def _check_retain_conditions(
        self, rt: AgentRuntime, trace: MemoryTrace
    ) -> RetainCondition | None:
        ctx = EngineContext(
            trace=trace, engine=self, now=rt.clock, agent_id=rt.agent_id
        )
        for cond in sorted(rt.retain_conditions, key=lambda c: -c.priority):
            try:
                if cond.evaluate(trace, ctx):
                    return cond
            except Exception:
                continue
        return None

    # ── Connectivity ──────────────────────────────────────

    def _compute_connectivity(self, rt: AgentRuntime, trace: MemoryTrace) -> int:
        count = 0
        for existing in rt.traces.values():
            if existing.is_deleted() or existing.id == trace.id:
                continue
            sim = rt.domain.similarity(
                self._to_content_for_comparison(trace),
                self._to_content_for_comparison(existing),
            )
            if sim > 0.5:
                count += 1
        return count

    def _compute_connectivity_for(self, rt: AgentRuntime, content: object) -> int:
        count = 0
        for existing in rt.traces.values():
            if existing.is_deleted():
                continue
            if rt.domain.similarity(content, existing.content) > 0.5:
                count += 1
        return count

    def _adjusted_lambda(self, connectivity: int) -> float:
        base = self._base_lambda()
        if connectivity >= 5:
            return base * 0.3
        elif connectivity >= 3:
            return base * 0.6
        elif connectivity >= 1:
            return base * 0.8
        else:
            return base

    # ── Thresholds & parameters ───────────────────────────

    @staticmethod
    def _base_lambda() -> float:
        return 0.02

    @staticmethod
    def _threshold_for_descend(layer: Layer) -> float:
        return {
            Layer.L0: 0.50,
            Layer.L1: 0.30,
            Layer.L2: 0.15,
            Layer.L3: 0.05,
        }[layer]

    # ── Soft delete & GC ──────────────────────────────────

    def _soft_delete(self, rt: AgentRuntime, trace: MemoryTrace) -> None:
        # Constraint facts are permanently retained
        if (
            isinstance(trace.content, L3_Fact)
            and trace.content.fact_type == "constraint"
        ):
            trace.deleted_at = None
            trace.deleted_wall_clock = None
            trace.layer = Layer.L3
            trace.decay_curve = DecayCurve(
                initial=1.0,
                lambda_=0.005,
                last_access=rt.clock,
                access_count=0,
            )
            return
        trace.deleted_at = rt.clock
        trace.deleted_wall_clock = now()

    def gc(self) -> int:
        """Global physical cleanup across all agents.

        Triple condition:
          1. M-Clock >= 1 volume since soft-delete
          2. AND (born > 90 real days ago OR deleted > 7 real days ago)
        Prevents premature GC of recently-created-then-deleted traces.
        """
        GC_M_WINDOW = TimePosition.M_PER_V
        GC_BORN_DAYS = 90
        GC_DELETED_DAYS = 7
        cutoff_born = now() - timedelta(days=GC_BORN_DAYS)
        cutoff_deleted = now() - timedelta(days=GC_DELETED_DAYS)
        total_deleted = 0

        for agent_id, rt in self.agents.items():
            to_delete: list[str] = []
            for tid, t in rt.traces.items():
                if t.deleted_at is None:
                    continue
                if (
                    isinstance(t.content, L3_Fact)
                    and t.content.fact_type == "constraint"
                ):
                    continue
                if rt.clock.distance_m(t.deleted_at) < GC_M_WINDOW:
                    continue
                # OR: born long ago, or deleted long enough ago
                if t.wall_clock_born < cutoff_born:
                    to_delete.append(tid)
                elif (
                    t.deleted_wall_clock is not None
                    and t.deleted_wall_clock < cutoff_deleted
                ):
                    to_delete.append(tid)

            for tid in to_delete:
                del rt.traces[tid]
            total_deleted += len(to_delete)

            if to_delete:
                self._log(
                    agent_id,
                    "gc",
                    to_delete,
                    f"GC purged {len(to_delete)} traces",
                    {"count": len(to_delete)},
                )

        return total_deleted

    def check_abandonment(self, agent_id: str) -> bool:
        rt = self._rt(agent_id)
        return (now() - rt.wall_clock_start).days >= 90

    # ── Capacity trigger ──────────────────────────────────

    def _maybe_trigger_capacity_check(self, rt: AgentRuntime, layer: Layer) -> None:
        capacity_limits = {
            Layer.L0: 15,
            Layer.L1: 30,
            Layer.L2: 20,
            Layer.L3: 50,
        }
        limit = capacity_limits.get(layer, 100)
        active = [
            t
            for t in rt.traces.values()
            if t.layer == layer and not t.is_deleted()
            and not _is_constraint_fact(t)
        ]

        if len(active) <= limit:
            return

        current = rt.clock
        active.sort(
            key=lambda t: (
                t.m_since_born(current)
                * (1.0 - t.retention(current))
                * (1.0 - t.significance)
            ),
            reverse=True,  # Highest score = most deserving to delete → first
        )
        # Descend head (most deserving), keep tail (least deserving) up to limit
        overflow = active[:-limit] if len(active) > limit else []

        if layer in (Layer.L0, Layer.L1):
            self._batch_descend(rt, overflow, layer)
        else:
            for v in overflow:
                self._descend(rt, v)

    # ── Utility methods ───────────────────────────────────

    def _to_content_for_comparison(self, obj: object) -> object:
        """Extract content for similarity comparison."""
        if hasattr(obj, "content"):
            return obj.content  # type: ignore[return-value]
        return obj

    def _active_traces(self, rt: AgentRuntime) -> list[MemoryTrace]:
        return [
            t
            for t in rt.traces.values()
            if t.layer in (Layer.L0, Layer.L1) and not t.is_deleted()
        ]

    def _latent_traces(self, rt: AgentRuntime) -> list[MemoryTrace]:
        return [
            t
            for t in rt.traces.values()
            if t.layer in (Layer.L2, Layer.L3) and not t.is_deleted()
        ]

    def _pattern_to_fact_kv(
        self, pattern: L2_Pattern, schema: dict
    ) -> tuple[str, object, str]:
        result = self._safe_llm_json(
            "将模式描述映射到 schema 的 key-value，并生成一句自然语言描述。"
            f"schema={schema}, 模式={pattern.description}"
            '返回 JSON: {"key": "...", "value": "...", "sentence": "..."}'
        )
        return (
            result.get("key", ""),
            result.get("value", ""),
            result.get("sentence", ""),
        )

    def _contrast_to_preference(
        self, pattern: L2_Pattern, schema: dict
    ) -> tuple[str, object, str]:
        return self._pattern_to_fact_kv(pattern, schema)

    def _matches_danger_signal(self, rt: AgentRuntime, text: str) -> bool:
        return rt.domain.is_danger_signal(text)

    def _has_conflict_with_newer(
        self, trace: MemoryTrace, rt: AgentRuntime
    ) -> bool:
        for other in rt.traces.values():
            if other.born_at <= trace.born_at or other.is_deleted():
                continue
            sim = rt.domain.similarity(
                self._to_content_for_comparison(trace),
                self._to_content_for_comparison(other),
            )
            if sim > 0.7:
                return True
        return False

    # ── Clustering helpers (L1→L2) ────────────────────────

    def _cluster_by_similarity(
        self,
        items: list[L1_Episode],
        similarity_fn,
        threshold: float,
    ) -> list[list[L1_Episode]]:
        """Greedy clustering by similarity threshold."""
        clusters: list[list[L1_Episode]] = []
        for item in items:
            best_cluster = None
            best_sim = threshold
            for c in clusters:
                avg_sim = mean_vals([similarity_fn(item, member) for member in c])
                if avg_sim > best_sim:
                    best_sim = avg_sim
                    best_cluster = c
            if best_cluster is not None:
                best_cluster.append(item)
            else:
                clusters.append([item])
        return clusters

    def _group_by_entity(
        self, episodes: list[L1_Episode]
    ) -> dict[str, list[L1_Episode]]:
        """Group episodes by subject_entity."""
        groups: dict[str, list[L1_Episode]] = {}
        for ep in episodes:
            groups.setdefault(ep.subject_entity, []).append(ep)
        return groups

    def _find_causal_chains(
        self, episodes: list[L1_Episode], max_depth: int
    ) -> list[list[L1_Episode]]:
        """Find chains where outcome of one episode ≈ subject_entity of the next."""
        chains: list[list[L1_Episode]] = []
        sorted_eps = sorted(episodes, key=lambda e: e.time)
        visited: set[int] = set()
        emb = self._embedding

        for i, start in enumerate(sorted_eps):
            if i in visited:
                continue
            chain = [start]
            current_ep = start
            for j in range(i + 1, len(sorted_eps)):
                if j in visited:
                    continue
                candidate = sorted_eps[j]
                sim = emb.similarity(
                    emb.embed(current_ep.outcome),
                    emb.embed(candidate.subject_entity),
                )
                if sim > 0.6:
                    chain.append(candidate)
                    visited.add(j)
                    current_ep = candidate
                    if len(chain) >= max_depth:
                        break
            if len(chain) >= 2:
                chains.append(chain)
                visited.add(i)

        return chains

    # ── LLM summarization helpers (L1→L2) ─────────────────

    def _summarize_frequency_pattern(
        self, cluster: list[L1_Episode]
    ) -> str:
        summaries = [
            f"- {ep.subject_entity}: {ep.predicate} → {ep.outcome}"
            for ep in cluster
        ]
        result = self._safe_llm_json(
            "总结以下事件的共同模式，用一句简短的话描述：\n" + "\n".join(summaries)
        )
        return result.get("description", summaries[0] if summaries else "")

    def _summarize_contrast_pattern(
        self, episodes: list[L1_Episode]
    ) -> str:
        summaries = [
            f"- {ep.subject_entity}: {ep.predicate} → {ep.outcome}"
            for ep in episodes
        ]
        result = self._safe_llm_json(
            "总结以下对同一实体的不同反馈，对比差异，用一句简短的话描述：\n"
            + "\n".join(summaries)
        )
        return result.get("description", summaries[0] if summaries else "")

    def _describe_chain(self, chain: list[L1_Episode]) -> str:
        steps = " → ".join(e.outcome for e in chain)
        return f"因果链：{chain[0].subject_entity} → {steps}"
