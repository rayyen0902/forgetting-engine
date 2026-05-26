"""Skincare domain adapter for the Forgetting Engine.

Implements the DomainAdapter interface for skincare consultation scenarios.
Includes entity extraction, domain-specific retain conditions, L1/L2 induction
strategies, conflict detection, and injection formatting.

Reference: forgetting_engine.pseudo:1325-2052
"""

from forgetting_engine.domain_adapter import DomainAdapter
from forgetting_engine.embedding import get_embedding
from forgetting_engine.models import (
    FactField,
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
from forgetting_engine.utils import _extract_text, _text_contains_any, cosine_sim

# P1-2: module-level embedder cache to avoid repeated get_embedding() on hot path
_EMBEDDER = None


def _get_cached_embedder():
    global _EMBEDDER
    if _EMBEDDER is None:
        from forgetting_engine.embedding import get_embedding

        _EMBEDDER = get_embedding()
    return _EMBEDDER


# P1-1: deterministic fingerprint for L1_Episode when real ID is not available
def _episode_fingerprint(ep: L1_Episode) -> str:
    import hashlib

    key = (
        f"{ep.subject_entity}|{ep.action_type}|{ep.predicate}|"
        f"{ep.outcome}|{ep.time.to_m()}"
    )
    return hashlib.sha256(key.encode()).hexdigest()[:12]


# ============================================================
# Config table 1: SKINCARE_ACTION_TYPES (30 types)
# ============================================================
# Pseudo-code line: 1416-1458

SKINCARE_ACTION_TYPES = [
    # Consultation
    "consult_skin_type",
    "consult_concern",
    "consult_product",
    "consult_routine",
    "consult_ingredient",
    "consult_seasonal",

    # Feedback
    "report_result_positive",
    "report_result_neutral",
    "report_result_negative",
    "report_reaction",
    "report_skin_change",

    # Behavior
    "log_routine",
    "log_product_start",
    "log_product_stop",
    "log_skin_status",

    # Decision
    "purchase_inquiry",
    "compare_products",
    "set_preference",
    "set_constraint",
    "request_timeline",

    # Emergency
    "emergency_breakout",
    "emergency_reaction",
    "emergency_burn",

    # Charter-required (section 4 article 4: refuse / advise / refer)
    "refuse_medical_request",
    "refer_to_clinic",
    "downgrade_to_basic_care",
    "report_high_risk_signal",
    "disclose_non_medical",
    "request_image_analysis",
    "disclose_image_boundary",
]


# ============================================================
# Config table 2: SKINCARE_DANGER_SIGNALS (45 signals, 7 groups A-G)
# ============================================================
# Pseudo-code line: 1463-1496

SKINCARE_DANGER_SIGNALS = [
    # -- A. Infection & acute inflammation --
    "\u8113\u75b1\u5bc6\u96c6",     # 脓疱密集
    "\u9ec4\u8272\u7ed3\u75c2",     # 黄色结痂
    "\u6e17\u51fa\u6d41\u6c34",     # 渗出流水
    "\u6076\u81ed",                 # 恶臭
    "\u7ea2\u80bf\u70ed\u75db",     # 红肿热痛
    "\u76ae\u80a4\u53d1\u70eb",     # 皮肤发烫
    "\u6c34\u75b1\u6210\u7c07",     # 水疱成簇
    "\u5ed3\u70c2\u9762\u6269\u5927",  # 糜烂面扩大
    "\u51fa\u8840\u4e0d\u6b62",     # 出血不止

    # -- B. Systemic spread --
    "\u76ae\u75b9\u6269\u6563",     # 皮疹扩散
    "\u5feb\u901f\u6269\u6563",     # 快速扩散
    "\u53d1\u70ed",                 # 发热
    "\u5bd2\u6218",                 # 寒战
    "\u6dcb\u5df4\u7ed3\u80bf\u5927",  # 淋巴结肿大
    "\u610f\u8bc6\u6a21\u7cca",     # 意识模糊

    # -- C. High-risk body sites --
    "\u773c\u5468\u7ea2\u80bf",     # 眼周红肿
    "\u89c6\u7269\u6a21\u7cca",     # 视物模糊
    "\u7741\u773c\u56f0\u96be",     # 睁眼困难
    "\u53e3\u5468\u5ed3\u70c2",     # 口周糜烂
    "\u9f3b\u5468\u5ed3\u70c2",     # 鼻周糜烂

    # -- D. Allergy & adverse drug reactions --
    "\u5927\u9762\u79ef\u98ce\u56e2",  # 大面积风团
    "\u9762\u90e8\u80bf\u80c0",     # 面部肿胀
    "\u5589\u5934\u7d27",           # 喉头紧
    "\u5598\u9e23",                 # 喘鸣
    "\u8868\u76ae\u5265\u8131",     # 表皮剥脱
    "\u5e7f\u6cdb\u6c34\u75b1",     # 广泛水疱
    "\u8fc7\u654f\u6027\u4f11\u514b",  # 过敏性休克
    "anaphylaxis",

    # -- E. Pigment & lesion high-risk signals --
    "\u9ed1\u75e3\u53d8\u5927",     # 黑痣变大
    "\u9ed1\u75e3\u53d8\u6df1",     # 黑痣变深
    "\u8fb9\u7f18\u4e0d\u89c4\u5219",  # 边缘不规则
    "\u7834\u6e83\u51fa\u8840",     # 破溃出血
    "\u65b0\u751f\u7269\u5feb\u901f\u589e\u957f",  # 新生物快速增长
    "\u53cd\u590d\u7834\u6e83\u4e0d\u6108",  # 反复破溃不愈

    # -- General high risk --
    "\u70c2\u8138",                 # 烂脸
    "\u707c\u70e7",                 # 灼烧
    "\u6e83\u70c2",                 # 溃烂
    "\u6fc0\u7d20\u8138",           # 激素脸
    "\u6fc0\u7d20\u4f9d\u8d56",     # 激素依赖
    "\u523a\u75db\u96be\u5fcd",     # 刺痛难忍
    "\u8131\u76ae\u4e25\u91cd",     # 脱皮严重
    "\u7ea2\u80bf\u4e0d\u9000",     # 红肿不退
    "\u5927\u9762\u79ef\u7206\u75d8",  # 大面积爆痘
    "\u5316\u8113",                 # 化脓
    "\u75a4\u75d5",                 # 疤痕

    # -- F/G. Special population trigger keywords --
    "\u5a74\u5e7c\u513f",           # 婴幼儿
    "\u5b55\u5987",                 # 孕妇
    "\u54fa\u4e73\u671f",           # 哺乳期
    "\u5907\u5b55",                 # 备孕
    "\u514d\u75ab\u6291\u5236",     # 免疫抑制
    "\u957f\u671f\u53e3\u670d\u7ef4A\u9178",  # 长期口服维A酸
    "\u5316\u7597",                 # 化疗
    "\u653e\u7597",                 # 放疗
    "\u767d\u8840\u75c5",           # 白血病
]


# ============================================================
# Config table 3: SKINCARE_FACT_SCHEMA
# ============================================================
# Pseudo-code line: 1349-1411
# Four categories: identity / preference / constraint / risk-profile

SKINCARE_FACT_SCHEMA: dict[str, FactField] = {
    # -- Identity --
    "skin_type": FactField(
        type="enum",
        values=["oily", "dry", "combination", "normal", "sensitive"],
    ),
    "skin_concerns": FactField(
        type="set",
        values=[
            "acne", "closed_comedones", "blackheads",
            "pores", "roughness",
            "redness", "rosacea", "eczema",
            "wrinkles", "firmness",
            "dullness", "uneven_tone", "dark_spots", "melasma",
            "dehydration", "oil_imbalance",
            "sensitivity", "allergy_prone",
        ],
    ),
    "oil_level": FactField(type="range", min=1, max=5),
    "hydration": FactField(type="range", min=1, max=5),
    "sensitivity": FactField(type="range", min=1, max=5),

    # -- Preference --
    "budget_level": FactField(
        type="enum", values=["drugstore", "mid_range", "premium", "luxury"],
    ),
    "texture_preference": FactField(
        type="set",
        values=["light", "fresh", "rich", "gel", "cream", "lotion", "balm", "oil"],
    ),
    "fragrance_preference": FactField(
        type="enum", values=["fragrance_free", "light_scent", "no_preference"],
    ),
    "brand_affinity": FactField(type="set", element="string"),
    "brand_avoid": FactField(type="set", element="string"),
    "routine_style": FactField(
        type="enum", values=["minimalist", "standard", "elaborate", "k_beauty"],
    ),
    "sunscreen_habit": FactField(
        type="enum", values=["daily", "outdoor_only", "occasional", "never"],
    ),
    "vegan_preference": FactField(type="boolean"),
    "alcohol_free_preference": FactField(type="boolean"),

    # -- Constraint --
    "allergies": FactField(type="set", element="ingredient"),
    "intolerances": FactField(type="set", element="ingredient"),
    "contraindicated_products": FactField(type="set", element="string"),
    "medical_conditions": FactField(type="set", element="string"),

    # -- Charter: risk profile (charter chapters 3 & 5) --
    "is_svip": FactField(type="boolean"),
    "special_protection": FactField(
        type="set",
        values=[
            "minor", "pregnant", "nursing", "trying_to_conceive",
            "immunosuppressed", "cancer_treatment", "oral_retinoid",
        ],
    ),
    "high_risk_flags": FactField(
        type="set",
        values=[
            "acute_infection", "systemic_spread", "eye_involved",
            "anaphylaxis_risk", "suspicious_lesion", "child",
        ],
    ),
    "image_analysis_performed": FactField(type="boolean"),
}


# ============================================================
# SkincareAdapter
# ============================================================
# Pseudo-code line: 1501-1766

class SkincareAdapter(DomainAdapter):
    """Domain adapter for skincare consultation.

    Key design:
    1. Similarity = entity Jaccard (0.45) + semantic cosine (0.55)
    2. Relevance varies by layer: L0 always 1.0, L1+ uses entity/keyword/semantic match
    3. Allergy/intolerance → constraint, immunity = 1e (effectively permanent)
    4. Feedback-class episodes get time-weighted relevance boost
    """

    # -- Class-level entity dictionary --
    # Pseudo-code line: 1702-1743
    _ENTITY_PATTERNS: dict[str, list[str]] = {
        "ingredient": [
            "\u6c34\u6768\u9178", "\u679c\u9178", "\u58ec\u4e8c\u9178", "\u674f\u4ec1\u9178",
            "\u7518\u9187\u9178", "\u4e73\u9178",
            "\u70df\u9170\u80fa", "\u7ef4A\u9187", "\u89c6\u9ec4\u9187",
            "A\u9187", "A\u9178", "A\u919b",
            "\u7ef4C", "VC", "\u6297\u574f\u8840\u9178", "\u4e59\u57fa\u7ef4C",
            "\u73bb\u5c3f\u9178", "\u900f\u660e\u8d28\u9178", "B5", "\u6cdb\u9187",
            "\u795e\u7ecf\u9170\u80fa",
            "\u80dc\u80bd", "\u591a\u80bd", "\u84dd\u94dc\u80dc\u80bd", "\u516d\u80dc\u80bd",
            "\u8336\u6811\u7cbe\u6cb9", "\u91d1\u7f15\u6885", "\u79ef\u96ea\u8349",
            "\u9a6c\u9f7f\u836c",
            "\u89d2\u9ca8\u70f7", "\u8377\u8377\u5df4\u6cb9", "\u73ab\u7470\u679c\u6cb9",
            "\u9152\u7cbe", "\u9999\u7cbe", "\u9632\u8150\u5242", "\u77ff\u7269\u6cb9",
            "\u867e\u9752\u7d20", "\u827e\u5730\u82ef", "\u5bcc\u52d2\u70ef",
            "\u4f9d\u514b\u591a\u56e0",
            "\u4f20\u660e\u9178", "\u718a\u679c\u82f7", "\u66f2\u9178", "377",
            "\u767d\u85dc\u82a6\u9187", "\u7eff\u8336\u591a\u915a", "\u67b8\u675e",
        ],
        "product_category": [
            "\u6d01\u9762", "\u6d17\u9762\u5976", "\u5378\u5986",
            "\u6c34", "\u7cbe\u534e", "\u4e73\u6db2", "\u9762\u971c",
            "\u9632\u6652", "\u9694\u79bb", "\u9762\u819c",
            "\u773c\u971c", "\u9888\u971c",
            "\u9178\u7c7b\u7cbe\u534e", "\u4fee\u590d\u971c", "\u4fdd\u6e7f\u971c",
            "\u63a7\u6cb9",
            "A\u9187\u7cbe\u534e", "VC\u7cbe\u534e", "B5\u7cbe\u534e",
            "\u70df\u9170\u80fa\u7cbe\u534e",
        ],
        "brand": [
            "\u7406\u80a4\u6cc9", "\u96c5\u6f3e", "\u9002\u4e50\u80a4",
            "\u4e1d\u5854\u8299", "\u73c2\u6da6",
            "\u4fee\u4e3d\u53ef", "\u6b27\u90a6\u742a",
            "ZO", "Jan Marini",
            "\u5170\u853b", "\u96c5\u8bd7\u5170\u9edb", "\u8d44\u751f\u5802",
            "CPB", "\u83b1\u73c0\u59ae",
            "HBN", "\u73c0\u83b1\u96c5", "\u8587\u8bfa\u5a1c",
            "\u7389\u6cfd", "\u76f8\u5b9c\u672c\u8349",
            "\u9732\u5f97\u6e05", "\u6b27\u83b1\u96c5", "OLAY",
            "\u5b9d\u62c9\u73cd\u9009",
            "\u8335\u8299\u7eb1", "IPSA", "\u9edb\u73c2", "ALBION",
            "SK-II", "\u6d77\u84dd\u4e4b\u8c1c", "\u8d6b\u83b2\u5a1c",
        ],
        "skin_concern": [
            "\u75d8\u75d8", "\u95ed\u53e3", "\u9ed1\u5934", "\u7c89\u523a",
            "\u75e4\u75ae",
            "\u7ea2\u8840\u4e1d", "\u6cdb\u7ea2", "\u654f\u611f", "\u523a\u75db",
            "\u6bdb\u5b54", "\u7c97\u7cd9", "\u6697\u6c89", "\u80a4\u8272\u4e0d\u5747",
            "\u75d8\u5370", "\u6591\u70b9",
            "\u7ec6\u7eb9", "\u76b1\u7eb9", "\u677e\u5f1b",
            "\u6cd5\u4ee4\u7eb9", "\u9c7c\u5c3e\u7eb9",
            "\u5e72\u71e5", "\u8d77\u76ae", "\u8131\u76ae",
            "\u51fa\u6cb9", "\u6cb9\u5149",
            "\u9ed1\u773c\u5708", "\u773c\u888b", "\u6cea\u6c9f",
        ],
    }

    # Lazy-init: entity_text -> category
    _FLAT_ENTITIES: dict[str, str] = {}
    _ENTITIES_INITIALIZED = False

    @classmethod
    def _init_entities(cls) -> None:
        if cls._ENTITIES_INITIALIZED:
            return
        for category, terms in cls._ENTITY_PATTERNS.items():
            for term in terms:
                cls._FLAT_ENTITIES[term.lower()] = category
        cls._ENTITIES_INITIALIZED = True

    # ============================================================
    # Interface method 1: action_types
    # ============================================================

    def action_types(self) -> list[str]:
        return SKINCARE_ACTION_TYPES

    # ============================================================
    # Interface method 2: fact_schema
    # ============================================================

    def fact_schema(self) -> dict[str, FactField]:
        return SKINCARE_FACT_SCHEMA

    # ============================================================
    # Interface method 3: danger_signals
    # ============================================================

    def danger_signals(self) -> list[str]:
        return SKINCARE_DANGER_SIGNALS

    # ============================================================
    # Interface method 4: activation_threshold
    # ============================================================
    # Pseudo-code line: 1523-1531

    def activation_threshold(self, layer: Layer) -> float:
        """L2 lower threshold (more patterns in skincare).
        L3 higher threshold (precision required for facts).
        """
        return {
            Layer.L2: 0.35,
            Layer.L3: 0.55,
        }.get(layer, 0.5)

    # ============================================================
    # Interface method 5: similarity
    # ============================================================
    # Pseudo-code line: 1535-1556

    def similarity(self, a: object, b: object) -> float:
        """Hybrid similarity: entity Jaccard (0.45) + semantic cosine (0.55)."""
        text_a = _extract_text(a)
        text_b = _extract_text(b)

        entities_a = self._extract_skincare_entities(text_a)
        entities_b = self._extract_skincare_entities(text_b)

        entity_sim = self._jaccard(entities_a, entities_b) if entities_a or entities_b else 0.0

        emb = _get_cached_embedder()
        semantic_sim = emb.similarity(emb.embed(text_a), emb.embed(text_b))

        return 0.45 * entity_sim + 0.55 * semantic_sim

    # ============================================================
    # Interface method 6: relevance
    # ============================================================
    # Pseudo-code line: 1560-1608

    def relevance(self, trace: MemoryTrace, context: RetrievalContext) -> float:
        """Layer-aware relevance scoring.

        L0: always 1.0 (active injection layer).
        L1+: entity match (0.4) + keyword match (0.2) + semantic match (0.4).
        Feedback-class episodes get time-weighted boost.
        """
        if trace.layer == Layer.L0:
            return 1.0

        trace_text = _extract_text(trace.content)
        trace_entities = self._extract_skincare_entities(trace_text)

        # Entity match
        cue_entities: set[str] = set()
        for cue in context.cues:
            cue_entities.update(self._extract_skincare_entities(cue.value))
        entity_score = self._jaccard(trace_entities, cue_entities)

        # Keyword match (P0-1 fixed: strip entity prefix before matching)
        keyword_score = 0.0
        all_cue_text = " ".join(c.value for c in context.cues)
        if all_cue_text:
            for entity in trace_entities:
                term = entity.split(":", 1)[-1]  # "ingredient:烟酰胺" → "烟酰胺"
                if term.lower() in all_cue_text.lower():
                    keyword_score += 0.3

        # Semantic match
        cue_tokens = " ".join(c.value for c in context.cues)
        emb = _get_cached_embedder()
        semantic_score = emb.similarity(emb.embed(trace_text), emb.embed(cue_tokens))

        # Composite: entity 0.4 + keyword 0.2 + semantic 0.4
        raw = 0.4 * entity_score + 0.2 * min(keyword_score, 1.0) + 0.4 * semantic_score

        # Time-weighted boost for feedback-class episodes
        # (design decision #3: use context.current_m instead of trace.m_since_born(trace.born_at))
        if isinstance(trace.content, L1_Episode):
            ep = trace.content
            if ep.action_type in (
                "report_result_positive", "report_result_negative",
                "report_reaction", "report_skin_change",
            ):
                m_since_born = context.current_m - trace.born_at.to_m()
                if m_since_born >= 0:
                    if m_since_born <= TimePosition.M_PER_V:
                        raw *= 1.5
                    elif m_since_born > TimePosition.M_PER_V * 2:
                        raw *= 0.7

        return min(raw, 1.0)

    # ============================================================
    # Interface method 7: extra_retain_conditions
    # ============================================================
    # Pseudo-code line: 1612-1697
    #
    # Priority cascade:
    #   explicit command(100) > danger signal(95) > charter red line(92)
    #   > special population(88) > allergy(85) > high-frequency(80)
    #   > constraint(75) > connectivity(60) > effective product(50)
    #   > skin profile(45) > primacy/recency(40) > feedback chain(30)

    def extra_retain_conditions(self) -> list[RetainCondition]:
        M = TimePosition
        return [
            RetainCondition(
                name="\u62a4\u80a4\u00b7\u8fc7\u654f/\u4e0d\u8010\u53d7\u58f0\u660e",
                priority=85,
                evaluate=lambda t, ctx: (
                    isinstance(t.content, L1_Episode)
                    and t.content.action_type == "report_reaction"
                    and t.content.emotional_tone <= -0.5
                ),
                immunity_m=M.M_PER_E,
            ),
            RetainCondition(
                name="\u62a4\u80a4\u00b7\u7ea6\u675f\u58f0\u660e",
                priority=75,
                evaluate=lambda t, ctx: _text_contains_any(t.content, [
                    "\u4e0d\u8010\u53d7", "\u8fc7\u654f", "\u4e0d\u80fd\u7528",
                    "\u4e25\u91cd\u8fc7\u654f",
                    "\u7981\u5fcc", "\u533b\u751f\u8bf4\u4e0d", "\u76ae\u80a4\u79d1",
                ]),
                immunity_m=M.M_PER_E,
            ),
            RetainCondition(
                name="\u62a4\u80a4\u00b7\u6709\u6548\u4ea7\u54c1\u786e\u8ba4",
                priority=50,
                evaluate=lambda t, ctx: (
                    isinstance(t.content, L1_Episode)
                    and t.content.action_type == "report_result_positive"
                    and t.content.emotional_tone >= 0.5
                ),
                immunity_m=M.M_PER_V * 2,
            ),
            RetainCondition(
                name="\u62a4\u80a4\u00b7\u80a4\u8d28/\u6863\u6848\u58f0\u660e",
                priority=45,
                evaluate=lambda t, ctx: (
                    isinstance(t.content, L1_Episode)
                    and t.content.action_type in (
                        "consult_skin_type", "set_preference",
                        "log_skin_status", "set_constraint",
                    )
                ),
                immunity_m=M.M_PER_V * 3,
            ),
            RetainCondition(
                name="\u62a4\u80a4\u00b7\u5baa\u7ae0\u786c\u7ea2\u7ebf",
                priority=92,
                evaluate=lambda t, ctx: (
                    isinstance(t.content, L1_Episode)
                    and t.content.action_type in (
                        "refuse_medical_request", "refer_to_clinic",
                        "downgrade_to_basic_care", "report_high_risk_signal",
                    )
                ),
                immunity_m=M.M_PER_E,
            ),
            RetainCondition(
                name="\u62a4\u80a4\u00b7\u7279\u6b8a\u4eba\u7fa4\u58f0\u660e",
                priority=88,
                evaluate=lambda t, ctx: _text_contains_any(t.content, [
                    "\u5b55\u5987", "\u54fa\u4e73\u671f", "\u5907\u5b55",
                    "\u5a74\u5e7c\u513f", "\u5316\u7597", "\u767d\u8840\u75c5",
                    "\u514d\u75ab\u6291\u5236", "\u957f\u671f\u53e3\u670d\u7ef4A\u9178",
                ]),
                immunity_m=M.M_PER_E,
            ),
            RetainCondition(
                name="\u62a4\u80a4\u00b7\u53cd\u9988\u94fe\u4fdd\u62a4",
                priority=30,
                # Design decision #4: source_episode_ids is list[str], can't iterate
                # for action_type. Only check type + confidence.
                evaluate=lambda t, ctx: (
                    isinstance(t.content, L2_Pattern)
                    and t.content.type == "cascade"
                    and t.content.confidence >= 0.6
                ),
                immunity_m=M.M_PER_V,
            ),
        ]

    # ============================================================
    # Entity extraction
    # ============================================================
    # Pseudo-code line: 1745-1766

    def _extract_skincare_entities(self, text: str) -> set[str]:
        """Extract skincare domain entities from text."""
        self._init_entities()
        found: set[str] = set()
        text_lower = text.lower()
        for term, category in self._FLAT_ENTITIES.items():
            if term in text_lower:
                found.add(f"{category}:{term}")
        return found

    def _jaccard(self, set_a: set, set_b: set) -> float:
        if not set_a and not set_b:
            return 0.0
        inter = len(set_a & set_b)
        union = len(set_a | set_b)
        return inter / union if union > 0 else 0.0


# ============================================================
# Helper class 1: SkincareL1Compressor
# ============================================================
# Pseudo-code line: 1771-1799


class SkincareL1Compressor:
    """Domain-specific post-processing after L0→L1 compression.

    Called after the engine's _compress_L0_to_L1() to add skincare-specific
    metadata to the episode.
    """

    @staticmethod
    def post_process(
        episode: L1_Episode,
        messages: list[L0_RawMessage],
    ) -> L1_Episode:
        """Post-process an L1 episode with skincare domain metadata.

        1. Extracts entity tags from the source messages.
        2. Marks trial-start when a report_* action has no prior product ref.

        Design decision #1: uses domain_tags dict, not a dedicated field.
        """
        all_text = " ".join(m.text for m in messages)
        adapter = SkincareAdapter()
        entities = adapter._extract_skincare_entities(all_text)

        # Trial start detection: first feedback about a new product
        is_trial = (
            episode.action_type.startswith("report_")
            and not any("product:" in e for e in entities)
        )
        episode.domain_tags["trial_start"] = is_trial

        # Attach extracted entity tags for downstream use
        episode.domain_tags["entities"] = sorted(entities)

        return episode


# ============================================================
# Helper class 2: SkincareL2InductionStrategy
# ============================================================
# Pseudo-code line: 1804-1950


class SkincareL2InductionStrategy:
    """Domain-specific L1→L2 pattern induction for skincare.

    On top of the engine's three generic strategies (frequency/contrast/cascade),
    skincare adds: product-effect pairs, ingredient-reaction chains, and
    cyclical patterns.
    """

    @staticmethod
    def extract_product_effect_pairs(
        episodes: list[L1_Episode],
        entity_extractor,
    ) -> list[L2_Pattern]:
        """Identify 'product → effect' pairs from episodes.

        e.g. 3 mentions of B5 → redness reduction → "B5 effective for redness"
        """
        patterns: list[L2_Pattern] = []
        product_effects: dict[str, list[L1_Episode]] = {}

        for ep in episodes:
            text = f"{ep.subject_entity} {ep.predicate} {ep.outcome}"
            entities = entity_extractor(text)
            products = [
                e for e in entities
                if e.startswith("brand:") or e.startswith("ingredient:")
            ]
            for p in products:
                product_effects.setdefault(p, []).append(ep)

        for product, eps in product_effects.items():
            if len(eps) < 2:
                continue
            positive = sum(1 for e in eps if e.emotional_tone > 0)
            negative = sum(1 for e in eps if e.emotional_tone < -0.3)
            confidence = len(eps) / (len(eps) + 2)  # Bayesian smoothing

            patterns.append(L2_Pattern(
                type="product_effect",
                description=(
                    f"\u4ea7\u54c1 {product}\uff1a{len(eps)} \u6b21\u63d0\u53ca\uff0c"
                    f"\u6b63\u9762 {positive} \u6b21 / \u8d1f\u9762 {negative} \u6b21"
                ),
                confidence=confidence,
                source_episode_ids=[_episode_fingerprint(e) for e in eps],
                evidence_count=len(eps),
                last_observed_at=eps[-1].time,
            ))

        return patterns

    @staticmethod
    def extract_ingredient_reactions(
        episodes: list[L1_Episode],
        entity_extractor,
        danger_signals: list[str],
    ) -> list[L2_Pattern]:
        """Identify ingredient → negative reaction associations.

        Multiple episodes with the same ingredient + negative/danger signals
        → potential intolerance.
        """
        patterns: list[L2_Pattern] = []
        ingredient_negatives: dict[str, list[L1_Episode]] = {}

        for ep in episodes:
            text = (
                f"{ep.subject_entity} {ep.predicate} "
                f"{ep.outcome} {ep.negation or ''}"
            )
            if ep.emotional_tone > -0.2:
                continue  # Only look at negatives

            entities = entity_extractor(text)
            ingredients = [e for e in entities if e.startswith("ingredient:")]

            is_negative = (
                ep.emotional_tone <= -0.5
                or any(sig in text for sig in danger_signals)
                or ep.action_type in ("report_reaction", "report_result_negative")
            )
            if not is_negative:
                continue

            for ing in ingredients:
                ingredient_negatives.setdefault(ing, []).append(ep)

        for ing, eps in ingredient_negatives.items():
            if len(eps) < 2:
                continue
            patterns.append(L2_Pattern(
                type="ingredient_reaction",
                description=(
                    f"\u6210\u5206 {ing} \u5173\u8054 {len(eps)} \u6b21\u8d1f\u9762\u53cd\u5e94\uff0c"
                    f"\u53ef\u80fd\u4e3a\u4e0d\u8010\u53d7\u6210\u5206"
                ),
                confidence=min(len(eps) / 3.0, 0.95),
                source_episode_ids=[_episode_fingerprint(e) for e in eps],
                evidence_count=len(eps),
                last_observed_at=eps[-1].time,
            ))

        return patterns

    @staticmethod
    def extract_cyclical_patterns(
        episodes: list[L1_Episode],
        entity_extractor,
    ) -> list[L2_Pattern]:
        """Identify cyclical patterns: same concern recurring at intervals.

        e.g. breakouts before period, seasonal sensitivity.
        """
        from forgetting_engine.utils import mean_vals, std_vals

        patterns: list[L2_Pattern] = []
        concern_episodes: dict[str, list[L1_Episode]] = {}

        for ep in episodes:
            text = f"{ep.subject_entity} {ep.outcome}"
            entities = entity_extractor(text)
            concerns = [e for e in entities if e.startswith("skin_concern:")]
            for c in concerns:
                concern_episodes.setdefault(c, []).append(ep)

        for concern, eps in concern_episodes.items():
            if len(eps) < 3:
                continue
            times = sorted([e.time.to_m() for e in eps])
            gaps = [times[i] - times[i - 1] for i in range(1, len(times))]
            if not gaps:
                continue
            mean_gap = mean_vals([float(g) for g in gaps])
            std_gap = std_vals([float(g) for g in gaps])
            cv = std_gap / mean_gap if mean_gap > 0 else 999.0

            if cv < 0.5 and mean_gap >= TimePosition.M_PER_C:
                patterns.append(L2_Pattern(
                    type="cyclical",
                    description=(
                        f"\u76ae\u80a4\u95ee\u9898 {concern} \u5448\u73b0\u5468\u671f\u6027\uff0c"
                        f"\u5e73\u5747\u95f4\u9694\u7ea6 {mean_gap / TimePosition.M_PER_C:.1f} \u7ae0"
                    ),
                    confidence=min(len(eps) / 5.0, 0.8),
                    source_episode_ids=[_episode_fingerprint(e) for e in eps],
                    evidence_count=len(eps),
                    last_observed_at=eps[-1].time,
                ))

        return patterns


# ============================================================
# Helper class 3: SkincareConflictDetector
# ============================================================
# Pseudo-code line: 1955-2006


class SkincareConflictDetector:
    """Domain-specific L3 conflict/contradiction detection for skincare.

    Complements the engine's generic _detect_conflicts (L3 ↔ L0) with
    skincare-specific checks: constraint vs current behavior.
    """

    @staticmethod
    def check_fact_vs_new_claim(
        existing_fact: L3_Fact,
        new_claim: L1_Episode,
    ) -> dict | None:
        """Check if an existing L3 fact conflicts with a new claim.

        Typical scenarios:
        - Old: skin_type=oily, New: "recently very dry"
          → Not a conflict, short-term fluctuation
        - Old: allergies includes "salicylic acid", New: "using SA wipes"
          → Conflict! User may have forgotten or developed tolerance
        - Old: intolerance includes "retinol", New: "built retinol tolerance"
          → Not a conflict, update
        """
        if existing_fact.fact_type != "constraint":
            return None

        key = existing_fact.key
        value = existing_fact.value

        if key not in ("allergies", "intolerances", "contraindicated_products"):
            return None

        adapter = SkincareAdapter()
        new_entities = adapter._extract_skincare_entities(
            f"{new_claim.subject_entity} {new_claim.predicate} {new_claim.outcome}"
        )

        # P0-2 fixed: clean entity prefix before matching
        clean_entities = {e.split(":", 1)[-1].lower() for e in new_entities}
        for val in (value if isinstance(value, list) else [value]):
            if val.lower() not in clean_entities:
                continue

            tolerance_keywords = [
                "\u5efa\u7acb\u4e86\u8010\u53d7",
                "\u73b0\u5728\u80fd\u7528\u4e86",
                "\u8131\u654f\u4e86",
                "\u8010\u53d7\u4e86",
            ]
            if any(kw in new_claim.outcome for kw in tolerance_keywords):
                return {
                    "conflict": False,
                    "action": "update",
                    "detail": (
                        f"\u7528\u6237\u58f0\u660e\u5bf9 {val} \u5df2\u5efa\u7acb\u8010\u53d7\uff0c"
                        f"\u5efa\u8bae\u964d\u4f4e constraint confidence"
                    ),
                }

            return {
                "conflict": True,
                "action": "warn",
                "detail": (
                    f"\u68c0\u6d4b\u5230\u77db\u76fe\uff1aL3 \u8bb0\u5f55\u300c{existing_fact.sentence}\u300d\uff0c"
                    f"\u4f46\u7528\u6237\u6b63\u5728\u4f7f\u7528\u542b {val} \u7684\u4ea7\u54c1\u3002\u8bf7\u4e3b\u52a8\u63d0\u9192\u3002"
                ),
            }

        return None


# ============================================================
# Helper class 4: SkincareInjectionFormatter
# ============================================================
# Pseudo-code line: 2011-2047


class SkincareInjectionFormatter:
    """Domain-specific injection formatting for skincare.

    Complements the engine's render_for_injection [current]/[background]/[attention]
    blocks with a user profile card for LLM context.
    """

    @staticmethod
    def format_skin_profile(facts: list[L3_Fact]) -> str:
        """Format L3 facts as a 'user profile card' for LLM injection.

        Example output:
        ┌─ User Profile ──────────────────┐
        │ Skin: oily · sensitive          │
        │ Concerns: acne · redness · spots │
        │ ⚠ Contraindications: niacinamide │
        │ Prefs: fragrance-free · gel     │
        └──────────────────────────────────┘
        """
        identity_facts = [f for f in facts if f.fact_type == "identity"]
        preference_facts = [f for f in facts if f.fact_type == "preference"]
        constraint_facts = [f for f in facts if f.fact_type == "constraint"]

        profile_lines: list[str] = []

        if identity_facts:
            profile_lines.append(
                f"\u80a4\u8d28\u6863\u6848\uff1a{' \u00b7 '.join(f.sentence for f in identity_facts)}"
            )

        if constraint_facts:
            profile_lines.append(
                f"\u26a0 \u7981\u5fcc\uff1a{' \u00b7 '.join(f.sentence for f in constraint_facts)}"
            )

        if preference_facts:
            profile_lines.append(
                f"\u504f\u597d\uff1a{' \u00b7 '.join(f.sentence for f in preference_facts)}"
            )

        return "\n".join(profile_lines) if profile_lines else ""
