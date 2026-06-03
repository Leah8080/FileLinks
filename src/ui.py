import sys

# ANSI Color constants
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"
RED = "\033[31m"
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

def print_success(message: str):
    print(f"{GREEN}✔ {message}{RESET}")

def print_info(message: str):
    print(f"{CYAN}ℹ {message}{RESET}")

def print_warning(message: str):
    print(f"{YELLOW}⚠ {message}{RESET}")

def print_error(message: str):
    print(f"{RED}✘ {message}{RESET}")

def print_step(message: str):
    print(f"\n{BOLD}{BLUE}➤ {message}{RESET}")

def ask_input(prompt: str) -> str:
    print(f"{BOLD}{CYAN}▶ {prompt}{RESET}", end="")
    return input().strip()
