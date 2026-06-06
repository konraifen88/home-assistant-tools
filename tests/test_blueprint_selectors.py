from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT_DIR = ROOT / "window-open-blueprint"

KNOWN_SELECTOR_TYPES = {
    "action",
    "app",
    "area",
    "attribute",
    "assist_pipeline",
    "backup_location",
    "boolean",
    "choose",
    "color_temp",
    "condition",
    "config_entry",
    "constant",
    "conversation_agent",
    "country",
    "date",
    "datetime",
    "device",
    "duration",
    "entity",
    "floor",
    "icon",
    "label",
    "language",
    "location",
    "media",
    "number",
    "object",
    "qr_code",
    "color_rgb",
    "select",
    "state",
    "statistic",
    "target",
    "template",
    "text",
    "theme",
    "time",
    "trigger",
}


def _input_constructor(loader, node):
    if isinstance(node, yaml.ScalarNode):
        return node.value
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    raise TypeError(f"Unsupported !input node: {type(node)!r}")


class BlueprintLoader(yaml.SafeLoader):
    pass


BlueprintLoader.add_constructor("!input", _input_constructor)


def _walk_selectors(value):
    if isinstance(value, dict):
        if "selector" in value:
            yield value["selector"]
        for child in value.values():
            yield from _walk_selectors(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_selectors(child)


class BlueprintSelectorTest(unittest.TestCase):
    def test_blueprint_selectors_use_known_types(self):
        for blueprint_path in BLUEPRINT_DIR.glob("*_blueprint.yaml"):
            with self.subTest(blueprint=blueprint_path.name):
                blueprint = yaml.load(
                    blueprint_path.read_text(encoding="utf-8"),
                    Loader=BlueprintLoader,
                )

                for selector in _walk_selectors(blueprint):
                    selector_types = set(selector)
                    unknown = selector_types - KNOWN_SELECTOR_TYPES
                    self.assertFalse(
                        unknown,
                        f"{blueprint_path.name} uses unknown selector type(s): {sorted(unknown)}",
                    )


if __name__ == "__main__":
    unittest.main()
