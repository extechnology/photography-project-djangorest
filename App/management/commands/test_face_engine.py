import sys
from django.core.management.base import BaseCommand
from App.face_engine import diagnose_face_engine, verify_opencv_compatibility, get_model_dir


class Command(BaseCommand):
    help = "Verifies OpenCV, YuNet face detector, and SFace recognizer health for production environments."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("=== Face Engine Production Health Diagnostic ==="))
        self.stdout.write(f"Python: {sys.version.split()[0]} ({sys.platform})")

        diag = diagnose_face_engine()

        self.stdout.write(f"Model Directory: {diag['model_dir']}")
        self.stdout.write("")

        all_passed = True
        for idx, check in enumerate(diag["checks"], start=1):
            passed = check["passed"]
            name = check["name"]
            detail = check["detail"]

            if passed:
                status_str = self.style.SUCCESS("[PASS]")
            else:
                status_str = self.style.ERROR("[FAIL]")
                all_passed = False

            self.stdout.write(f"{status_str} {idx}. {name}")
            self.stdout.write(f"       Detail: {detail}")

        self.stdout.write("")
        if all_passed:
            self.stdout.write(self.style.SUCCESS("✓ All FaceEngine diagnostics PASSED. System is production-ready."))
        else:
            self.stdout.write(self.style.ERROR("✗ FaceEngine diagnostics FAILED. Please review failed checks above."))
            sys.exit(1)
