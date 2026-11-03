"""Size Preset Picker: pick width/height from a fixed list of presets, with a visual grid in the UI."""

# (width, height)
PRESETS = [
    # Portrait
    (768, 1024),
    (832, 1248),
    (840, 1256),
    (864, 1248),
    (896, 1152),
    (1024, 1280),
    (1024, 1536),
    (1024, 1568),
    (1080, 1920),
    (1088, 1920),
    (1216, 1472),
    (1224, 1472),
    (1296, 1728),
    (1304, 1752),
    (1360, 2048),
    (1440, 2160),
    (1728, 2160),
    # Square
    (1048, 1048),
    (1120, 1120),
    (1536, 1536),
    (2048, 2048),
    # Landscape
    (1368, 768),
    (1920, 1080),
    (1928, 1088),
]

CUSTOM = "Custom"
LABELS = [f"{w} x {h}" for w, h in PRESETS]
DEFAULT = "1224 x 1472"


class SizePresetPicker:
    @classmethod
    def INPUT_TYPES(cls):
        size = {"min": 64, "max": 8192, "step": 8}
        return {
            "required": {
                "preset": (LABELS + [CUSTOM], {
                    "default": DEFAULT,
                    # Read by web/size_preset_picker.js to draw the tile grid.
                    "presets_meta": [{"label": l, "w": w, "h": h} for l, (w, h) in zip(LABELS, PRESETS)],
                }),
                # Only used when preset is "Custom". The UI fills these in when a preset is picked,
                # and switches to "Custom" when they are edited by hand.
                "custom_width": ("INT", {"default": 1224, **size}),
                "custom_height": ("INT", {"default": 1472, **size}),
            }
        }

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("width", "height")
    FUNCTION = "pick"
    CATEGORY = "utils"

    def pick(self, preset, custom_width, custom_height):
        if preset == CUSTOM:
            return (custom_width, custom_height)
        w, h = (int(v) for v in preset.lower().split("x"))
        return (w, h)


NODE_CLASS_MAPPINGS = {"SizePresetPicker": SizePresetPicker}
NODE_DISPLAY_NAME_MAPPINGS = {"SizePresetPicker": "Size Preset Picker"}
