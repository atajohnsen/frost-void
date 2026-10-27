# Source from ~/.bashrc. Two-line monochrome prompt, inspired by your reference.
__frost_prompt() {
    local status="$?" accent="121;162;144" muted="130;140;148" reset='\[\e[0m\]'
    local palette="${XDG_CONFIG_HOME:-$HOME/.config}/frost/generated/palette.json"
    # A small Python process runs once per prompt; no command runs while typing.
    if [[ -r "$palette" ]]; then
        accent=$(python3 -c 'import json,sys;c=json.load(open(sys.argv[1]))["accent"];print(";".join(str(int(c[i:i+2],16)) for i in (1,3,5)))' "$palette")
    fi
    PS1="\[\e[38;2;${accent}m\]◉ \u${reset} \[\e[38;2;${muted}m\]at${reset} \w"
    if (( status != 0 )); then PS1+=" \[\e[38;2;${accent}m\]${status}${reset}"; fi
    PS1+="\n\[\e[38;2;${accent}m\]╰─➜${reset} "
}
if [[ ${PROMPT_COMMAND-} != *"__frost_prompt"* ]]; then
    PROMPT_COMMAND="__frost_prompt${PROMPT_COMMAND:+; $PROMPT_COMMAND}"
fi
