from __future__ import annotations

import argparse
import json

from app.autoresearch import run_autoresearch_loop
from app.config import Settings
from app.db import build_database_state, init_database
from app.services import default_profile_payload, refresh_validation_report, seed_demo_content, seed_universe
from app.user_service import acknowledge_disclosures, create_or_update_profile, ensure_bootstrap_admin


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Cassandra AutoResearch loop")
    parser.add_argument("--compact", action="store_true", help="Print compact JSON instead of pretty output")
    args = parser.parse_args()

    settings = Settings()
    database = build_database_state(settings)
    init_database(database, auto_create_schema=settings.auto_create_schema)
    with database.session_factory() as session:
        admin_user = ensure_bootstrap_admin(session, settings)
        seed_universe(session)
        seed_demo_content(session, settings)
        if admin_user is not None:
            if admin_user.profile is None:
                create_or_update_profile(session, admin_user, default_profile_payload())
            if admin_user.disclosures_acknowledged_at is None:
                acknowledge_disclosures(session, admin_user)
        refresh_validation_report(session, settings)
        artifact = run_autoresearch_loop(session, settings)
    if args.compact:
        print(json.dumps(artifact, sort_keys=True))
    else:
        print(json.dumps(artifact, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
