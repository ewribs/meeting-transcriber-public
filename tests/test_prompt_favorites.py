import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_settings
import prompt_favorites


class PromptFavoritesTests(
    unittest.TestCase
):
    def test_builtins_are_always_present(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = (
                Path(tmp) / "settings.json"
            )

            with patch.object(
                app_settings,
                "SETTINGS_PATH",
                settings_path,
            ), patch.object(
                prompt_favorites,
                "load_app_settings",
                lambda: app_settings.load_app_settings(
                    settings_path
                ),
            ):
                favorites = (
                    prompt_favorites
                    .load_prompt_favorites()
                )

        self.assertGreaterEqual(
            len(favorites),
            7,
        )
        self.assertTrue(
            all(
                item["built_in"]
                for item in favorites
            )
        )

    def test_custom_favorites_persist(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = (
                Path(tmp) / "settings.json"
            )

            def load():
                return (
                    app_settings
                    .load_app_settings(
                        settings_path
                    )
                )

            def save(settings):
                return (
                    app_settings
                    .save_app_settings(
                        settings,
                        settings_path
                    )
                )

            with patch.object(
                prompt_favorites,
                "load_app_settings",
                load,
            ), patch.object(
                prompt_favorites,
                "save_app_settings",
                save,
            ):
                saved = (
                    prompt_favorites
                    .save_custom_prompt_favorites(
                        [
                            {
                                "id": "custom.1",
                                "title": "My Brief",
                                "prompt": "Summarize it.",
                            }
                        ]
                    )
                )

                reloaded = (
                    prompt_favorites
                    .load_prompt_favorites()
                )

        custom_saved = [
            item
            for item in saved
            if not item["built_in"]
        ]
        custom_reloaded = [
            item
            for item in reloaded
            if not item["built_in"]
        ]

        self.assertEqual(
            custom_saved,
            custom_reloaded,
        )
        self.assertEqual(
            custom_reloaded[0]["title"],
            "My Brief",
        )

    def test_invalid_and_builtin_ids_are_not_saved(
        self,
    ):
        cleaned = (
            prompt_favorites
            .normalize_custom_favorites(
                [
                    {
                        "id": "builtin.bad",
                        "title": "No",
                        "prompt": "No",
                    },
                    {
                        "id": "",
                        "title": "No",
                        "prompt": "No",
                    },
                    {
                        "id": "custom.ok",
                        "title": "Okay",
                        "prompt": "Do this.",
                    },
                ]
            )
        )

        self.assertEqual(
            [item["id"] for item in cleaned],
            ["custom.ok"],
        )



    def test_changes_favorite_uses_changes_mode(
        self,
    ):
        favorites = [
            prompt_favorites
            ._with_category(item)
            for item
            in prompt_favorites
                .BUILTIN_FAVORITES
        ]

        changes = next(
            item
            for item in favorites
            if item["id"]
            == "builtin.changes"
        )

        self.assertEqual(
            changes["category"],
            "changes",
        )
        self.assertIn(
            "latest meeting",
            changes["prompt"],
        )

    def test_boss_1v1_recipe_is_available(
        self,
    ):
        favorites = [
            prompt_favorites
            ._with_category(item)
            for item
            in prompt_favorites
                .BUILTIN_FAVORITES
        ]

        recipe = next(
            item
            for item in favorites
            if item["id"]
            == "builtin.boss_1v1_prep"
        )

        self.assertEqual(
            recipe["category"],
            "recipe",
        )
        self.assertIn(
            "Sensitive / escalation topics",
            recipe["prompt"],
        )
        self.assertIn(
            "Ad-hoc signals",
            recipe["prompt"],
        )
        self.assertIn(
            "Never include a staff member's own commitments here",
            recipe["prompt"],
        )
        self.assertIn(
            "Do not present challenges or unfinished work as wins",
            recipe["prompt"],
        )


if __name__ == "__main__":
    unittest.main()
