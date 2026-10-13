def configure_workbench(
    args,
) -> None:
    print()
    print("Meeting Memory Workbench")
    print("------------------------")
    print(
        "Leave any filter blank "
        "to ignore it."
    )
    print()

    args.person = input(
        "Person: "
    ).strip() or None

    args.start_date = input(
        "Start date (YYYY-MM-DD): "
    ).strip() or None

    args.end_date = input(
        "End date (YYYY-MM-DD): "
    ).strip() or None

    args.topic = input(
        "Topic: "
    ).strip() or None

    print()

    session_name = input(
        "Session name "
        "(blank for temporary chat): "
    ).strip()

    if session_name:
        args.session = session_name

    args.selection_criteria = {
        "person": args.person,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "topic": args.topic,
    }

    args.select = True
    args.chat = True
