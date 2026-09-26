# vhs tape for the ansel CLI demo GIF.
#
# Records a tour of the command surface using --help only, so it needs no
# Photos library, no Full Disk Access, and exposes nothing personal.
#
# Regenerate with:  vhs docs/cli-demo.tape   (from the repo root)
# Output:           docs/cli-demo.gif

Output docs/cli-demo.gif

Set Shell "zsh"
Set FontSize 16
Set Width 1100
Set Height 760
Set Theme "Catppuccin Mocha"
Set Padding 24
Set TypingSpeed 55ms
Set PlaybackSpeed 1.0

# Put the project venv on PATH so we can type `ansel` (not `uv run ansel`).
Hide
Type "export PATH=$PWD/.venv/bin:$PATH" Enter
Type "clear" Enter
Show

Sleep 600ms
Type "ansel --help"  Sleep 500ms  Enter  Sleep 3s

Type "ansel review --help"  Sleep 400ms  Enter  Sleep 2.5s

Type "ansel random --help"  Sleep 400ms  Enter  Sleep 3.5s

Type "ansel chunk --help"  Sleep 400ms  Enter  Sleep 2.5s

Type "ansel stats --help"  Sleep 400ms  Enter  Sleep 2.5s

Sleep 1.5s
