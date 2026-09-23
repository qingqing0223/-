from pathlib import Path
import unittest


class KuaishouBootstrapContractTests(unittest.TestCase):
    def test_windows_powershell_native_stderr_does_not_abort_bootstrap(self):
        text = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "bootstrap_kuaishou_session_windows.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn('$oldErrorActionPreference = $ErrorActionPreference', text)
        self.assertIn('$ErrorActionPreference = "Continue"', text)
        self.assertIn('$ErrorActionPreference = $oldErrorActionPreference', text)
        self.assertIn('Pop-Location', text)
        self.assertIn('$rc = $LASTEXITCODE', text)


if __name__ == "__main__":
    unittest.main()
