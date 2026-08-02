from app.application.environment_diagnostics import EnvironmentDiagnostics
from app.application.startup_result import StartupMode, StartupStatus
from app.application.startup_service import StartupService


def main() -> int:
    startup = StartupService(diagnostics=EnvironmentDiagnostics()).check(
        StartupMode.DIAGNOSTICS
    )
    print(startup.message)
    if startup.diagnostics is not None:
        for item in startup.diagnostics.items:
            version = f" ({item.version})" if item.version else ""
            print(f"{item.name}: {item.status.value}{version}")
    return 2 if startup.status is StartupStatus.BLOCKED else startup.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
