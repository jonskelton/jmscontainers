# shellcheck shell=bash
# Bash completion for a checkout installation of jms.
# shellcheck disable=SC2207  # completion words are fixed, spaceless tokens
# shellcheck disable=SC2034  # _init_completion assigns the standard locals
# Workdir operands are ordinary paths, so complete directories for the
# positional and for anything following -w/--workdir.
_jms_dirs() {
    [[ $cur == -* ]] && return
    [[ $prev == -b || $prev == --bin || $prev == -n || $prev == --name ]] && return
    _filedir -d
}

_jms_completion() {
    local cur prev words cword
    _init_completion -n : || return
    local commands='build launch inspect trust init clean'
    if (( cword == 1 )); then
        COMPREPLY=( $(compgen -W "$commands" -- "$cur") )
        return
    fi
    case ${words[1]} in
        trust)
            COMPREPLY=( $(compgen -W 'list revoke prune --fingerprint --auth --no-auth --purge-images' -- "$cur") )
            [[ $cur != -* ]] && _filedir -d ;;
        clean)
            COMPREPLY=( $(compgen -W '-w --workdir --all --images --dry-run' -- "$cur") )
            _jms_dirs ;;
        build)
            COMPREPLY=( $(compgen -W '-w --workdir --base --trust --no-auth --no-cache --pull' -- "$cur") )
            _jms_dirs ;;
        launch)
            COMPREPLY=( $(compgen -W '-w --workdir --trust --auth --no-auth --no-cache -r --root -b --bin -n --name' -- "$cur") )
            _jms_dirs ;;
        inspect)
            COMPREPLY=( $(compgen -W '-w --workdir' -- "$cur") )
            _jms_dirs ;;
        init)
            COMPREPLY=( $(compgen -W '-w --workdir --with-manifest' -- "$cur") )
            _jms_dirs ;;
    esac
}
complete -F _jms_completion jms
