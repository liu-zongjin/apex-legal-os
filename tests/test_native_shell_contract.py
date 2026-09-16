from pathlib import Path
import unittest


class NativeShellContractTests(unittest.TestCase):
    def test_native_shell_recovers_webkit_content_process(self):
        source = (Path(__file__).parents[1] / "native-shell" / "Sources" / "main.swift").read_text()
        self.assertIn("webViewWebContentProcessDidTerminate", source)
        self.assertIn("webContentRecoveryTimes.count <= 3", source)
        self.assertIn("loadFreshApplicationDocument", source)

    def test_native_shell_exposes_web_editing_undo_and_redo(self):
        source = (Path(__file__).parents[1] / "native-shell" / "Sources" / "main.swift").read_text()
        self.assertIn('NSMenuItem(title: "撤销", action: #selector(performUndo(_:)), keyEquivalent: "z")', source)
        self.assertIn('NSMenuItem(title: "重做", action: #selector(performRedo(_:)), keyEquivalent: "z")', source)
        self.assertIn("activeUndoManager()?.undo()", source)
        self.assertIn("activeUndoManager()?.redo()", source)
        self.assertIn("redoItem.keyEquivalentModifierMask = [.command, .shift]", source)


if __name__ == "__main__":
    unittest.main()
