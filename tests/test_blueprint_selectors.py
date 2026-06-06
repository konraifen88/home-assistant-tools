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


def _walk_targets(value):
    if isinstance(value, dict):
        if "target" in value:
            yield value["target"]
        for child in value.values():
            yield from _walk_targets(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_targets(child)


def _walk_choose_actions(value):
    if isinstance(value, dict):
        if "choose" in value:
            yield value
        for child in value.values():
            yield from _walk_choose_actions(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_choose_actions(child)


def _collect_input_defaults(value):
    defaults = {}
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, dict) and "selector" in child and "default" in child:
                defaults[key] = child["default"]
            defaults.update(_collect_input_defaults(child))
    elif isinstance(value, list):
        for child in value:
            defaults.update(_collect_input_defaults(child))
    return defaults


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

    def test_empty_default_inputs_are_not_used_directly_as_target_entity_id(self):
        for blueprint_path in BLUEPRINT_DIR.glob("*_blueprint.yaml"):
            with self.subTest(blueprint=blueprint_path.name):
                blueprint = yaml.load(
                    blueprint_path.read_text(encoding="utf-8"),
                    Loader=BlueprintLoader,
                )
                input_defaults = _collect_input_defaults(blueprint["blueprint"]["input"])
                empty_default_inputs = {
                    key for key, value in input_defaults.items() if value == ""
                }

                for target in _walk_targets(blueprint):
                    entity_id = target.get("entity_id")
                    self.assertNotIn(
                        entity_id,
                        empty_default_inputs,
                        f"{blueprint_path.name} uses optional input {entity_id!r} directly in target.entity_id",
                    )

    def test_choose_entries_have_conditions_and_sequence(self):
        for blueprint_path in BLUEPRINT_DIR.glob("*_blueprint.yaml"):
            with self.subTest(blueprint=blueprint_path.name):
                blueprint = yaml.load(
                    blueprint_path.read_text(encoding="utf-8"),
                    Loader=BlueprintLoader,
                )

                for choose_action in _walk_choose_actions(blueprint):
                    self.assertIsInstance(choose_action["choose"], list)
                    for branch in choose_action["choose"]:
                        self.assertNotIn(
                            "default",
                            branch,
                            f"{blueprint_path.name} places default inside a choose branch",
                        )
                        self.assertIn("conditions", branch)
                        self.assertIn("sequence", branch)


if __name__ == "__main__":
    unittest.main()
