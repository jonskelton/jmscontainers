# shellcheck shell=bash
# Bash completion for a checkout installation of jms.
# shellcheck disable=SC2207  # completion words are fixed, spaceless tokens
# shellcheck disable=SC2034  # _init_completion assigns the standard locals
#
# Completion follows the argument position: an option's value gets only what
# that option takes (directories after -w/--workdir, nothing after -b, -n or
# --fingerprint); directories are offered as an operand only where the
# command accepts a PATH and none was given yet; and nothing is offered after
# `--`, since the rest of a launch line belongs to the launched program.

_jms_completion() {
    local cur prev words cword
    _init_completion -n : || return
    if (( cword == 1 )); then
        COMPREPLY=( $(compgen -W 'build launch inspect trust init clean -h --help --version' -- "$cur") )
        return
    fi
    local i first operands=0
    for (( i = 2; i < cword; i++ )); do
        case ${words[i]} in
            --) return ;;
            # -w PATH stands in for the operand; the others just take a value.
            -w|--workdir) i=$(( i + 1 )); operands=$(( operands + 1 )) ;;
            -b|--bin|-n|--name|--fingerprint) i=$(( i + 1 )) ;;
            -*) ;;
            # Post-increment is false only for the first operand.
            *) (( operands++ )) || first=${words[i]} ;;
        esac
    done
    case $prev in
        -w|--workdir) _filedir -d; return ;;
        -b|--bin|-n|--name|--fingerprint) return ;;
    esac
    local opts dirs=0
    case ${words[1]} in
        build) opts='-w --workdir --base --trust --no-auth --no-cache --pull' ;;
        launch)
            opts='-w --workdir --trust --auth --no-auth --no-cache --no-network --git-writable -r --root -b --bin -n --name'
            (( operands == 0 )) && dirs=1 ;;
        inspect)
            opts='-w --workdir'
            (( operands == 0 )) && dirs=1 ;;
        trust)
            if (( operands == 0 )); then
                opts='list revoke prune --fingerprint --auth --no-auth'; dirs=1
            else
                case $first in
                    list|prune) return ;;
                    revoke) opts='--purge-images'; (( operands == 1 )) && dirs=1 ;;
                    *) opts='--fingerprint --auth --no-auth' ;;
                esac
            fi ;;
        init) opts='-w --workdir --with-manifest' ;;
        clean) opts='-w --workdir --all --images --dry-run' ;;
        *) return ;;
    esac
    COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
    if (( dirs )) && [[ $cur != -* ]]; then
        _filedir -d
    fi
}
complete -F _jms_completion jms
