"""M-Clock: narrative time in agent interaction density.

8-base progression: moment → scene → chapter → volume → era.
Internal calculation always in m (moment). Display as hierarchical tags.
"""

from dataclasses import dataclass


@dataclass
class TimePosition:
    """Agent narrative time coordinate.

    8-base carry:
      8m = 1s, 8s = 1c, 8c = 1v, 8v = 1e
    """

    e: int = 0  # era       4096m
    v: int = 0  # volume     512m
    c: int = 0  # chapter     64m
    s: int = 0  # scene        8m
    m: int = 0  # moment       1m

    # Carry constants
    M_PER_S: int = 8  # noqa: RUF012
    M_PER_C: int = 64  # noqa: RUF012
    M_PER_V: int = 512  # noqa: RUF012
    M_PER_E: int = 4096  # noqa: RUF012

    def __post_init__(self):
        self._normalize()

    def _normalize(self) -> None:
        """Carry overflow so each unit stays within its range."""
        # Carry moments to scenes
        if self.m >= self.M_PER_S:
            self.s += self.m // self.M_PER_S
            self.m = self.m % self.M_PER_S
        # Carry scenes to chapters
        if self.s >= 8:
            self.c += self.s // 8
            self.s = self.s % 8
        # Carry chapters to volumes
        if self.c >= 8:
            self.v += self.c // 8
            self.c = self.c % 8
        # Carry volumes to eras
        if self.v >= 8:
            self.e += self.v // 8
            self.v = self.v % 8

    @classmethod
    def from_m(cls, total: int) -> "TimePosition":
        e = total // cls.M_PER_E
        rest = total % cls.M_PER_E
        v = rest // cls.M_PER_V
        rest %= cls.M_PER_V
        c = rest // cls.M_PER_C
        rest %= cls.M_PER_C
        s = rest // cls.M_PER_S
        m = rest % cls.M_PER_S
        return cls(e=e, v=v, c=c, s=s, m=m)

    def to_m(self) -> int:
        return (
            self.e * self.M_PER_E
            + self.v * self.M_PER_V
            + self.c * self.M_PER_C
            + self.s * self.M_PER_S
            + self.m
        )

    def distance_m(self, other: "TimePosition") -> int:
        """Distance in m between two time positions."""
        return self.to_m() - other.to_m()

    def add_m(self, delta: int) -> "TimePosition":
        return TimePosition.from_m(self.to_m() + delta)

    def __str__(self) -> str:
        return f"e{self.e}.v{self.v}.c{self.c}.s{self.s}.m{self.m}"

    def __repr__(self) -> str:
        return str(self)

    def __hash__(self) -> int:
        return hash(self.to_m())

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TimePosition):
            return NotImplemented
        return self.to_m() == other.to_m()

    def __lt__(self, other: "TimePosition") -> bool:
        return self.to_m() < other.to_m()

    def __le__(self, other: "TimePosition") -> bool:
        return self.to_m() <= other.to_m()

    def __gt__(self, other: "TimePosition") -> bool:
        return self.to_m() > other.to_m()

    def __ge__(self, other: "TimePosition") -> bool:
        return self.to_m() >= other.to_m()
