"""Pequenos helpers usados pela interface de terminal."""

def ask_yes_no(prompt):
    return input(f"{prompt} (y/n) ").strip().lower() in ("yes", "y", "s", "sim")


def choose_from_list(options, prompt="Enter your choice: "):
    """Mostra a lista numerada e retorna o índice escolhido (0-based)."""
    while True:
        try:
            choice = int(input(prompt))
            if 1 <= choice <= len(options):
                return choice - 1
            print("Invalid choice. Please try again.")
        except ValueError:
            print("Invalid input. Please enter a number.")


def describe(creds):
    where = creds["hostname"] or creds["database"]
    return f"{creds['type']} @ {where}"
