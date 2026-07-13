"""
Shared filtering rules used by both the loose-resource stripper and the
.xcassets catalog filter.

An "idiom" here means an iOS/Xcode device idiom string as used in asset
catalog Contents.json files and (informally) in loose-resource filename
suffixes:

    universal, iphone, ipad, mac (Mac Catalyst / "mac-idiom" or scale=2x mac),
    tv, watch, watch-marketing, car (CarPlay)

Legacy device resources refers to older, no-longer-relevant variants such as
~ipad slices for apps that have dropped iPad support, 1x (non-Retina) images
now that all supported hardware is Retina+, or armv7/32-bit binary slices.
"""

from __future__ import annotations

from dataclasses import dataclass, field


ALL_IDIOMS = {"universal", "iphone", "ipad", "mac", "tv", "watch", "watch-marketing", "car"}
ALL_SCALES = {"1x", "2x", "3x"}
ALL_APPEARANCES = {"light", "dark", "tinted", "any"}  # "any" == no appearance restriction
ALL_ARCHS = {"arm64", "arm64e", "armv7", "armv7s", "x86_64", "i386"}


@dataclass
class FilterRules:
    """Rules describing what should be REMOVED.

    Anything named here is dropped; anything not named is kept. Empty sets
    mean "remove nothing of this kind".
    """

    remove_idioms: set = field(default_factory=set)
    keep_scales: set = field(default_factory=lambda: set(ALL_SCALES))
    remove_appearances: set = field(default_factory=set)
    keep_archs: set = field(default_factory=lambda: {"arm64", "arm64e"})

    def __post_init__(self):
        bad = self.remove_idioms - ALL_IDIOMS
        if bad:
            raise ValueError(f"Unknown idiom(s): {sorted(bad)}. Valid: {sorted(ALL_IDIOMS)}")
        bad = self.keep_scales - ALL_SCALES
        if bad:
            raise ValueError(f"Unknown scale(s): {sorted(bad)}. Valid: {sorted(ALL_SCALES)}")
        bad = self.remove_appearances - ALL_APPEARANCES
        if bad:
            raise ValueError(
                f"Unknown appearance(s): {sorted(bad)}. Valid: {sorted(ALL_APPEARANCES)}"
            )
        bad = self.keep_archs - ALL_ARCHS
        if bad:
            raise ValueError(f"Unknown arch(es): {sorted(bad)}. Valid: {sorted(ALL_ARCHS)}")

    @property
    def drop_scales(self) -> set:
        return ALL_SCALES - self.keep_scales

    def should_drop_idiom(self, idiom: str | None) -> bool:
        if not idiom:
            return False
        return idiom.lower() in self.remove_idioms

    def should_drop_scale(self, scale: str | None) -> bool:
        if not scale:
            return False
        return scale.lower() in self.drop_scales

    def should_drop_appearance(self, appearance: str | None) -> bool:
        if not appearance:
            return False
        return appearance.lower() in self.remove_appearances

    @classmethod
    def parse_csv(cls, value: str) -> set:
        if not value:
            return set()
        return {v.strip().lower() for v in value.split(",") if v.strip()}
