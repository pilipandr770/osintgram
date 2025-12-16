import app as app_module
from models import InstagramAccount, DmAssistantSettings


def main() -> None:
    flask_app = app_module.create_app()
    with flask_app.app_context():
        accs = InstagramAccount.query.all()
        print(f"Accounts: {len(accs)}")
        for a in accs:
            print(f"- {a.id} user={a.user_id} @{a.instagram_username} is_active={getattr(a, 'is_active', None)}")

        rows = DmAssistantSettings.query.all()
        print(f"\nDmAssistantSettings: {len(rows)}")
        for s in rows:
            print(
                f"- {s.id} user={s.user_id} account={s.instagram_account_id} "
                f"enabled={bool(s.enabled)} last_run={s.last_run_at} last_error={(s.last_error or '')}"
            )


if __name__ == '__main__':
    main()
