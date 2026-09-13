# The add_source / update_source / remove_source lifecycle, including the
# drift that previously had no recovery path short of rm -rf sources/<name>.

suite "sources"

sandbox_init

EXT="$SB/ext"
make_source_repo "$EXT" \
  'alpha-skill:Does alpha things.' \
  'beta-skill:Says "hello there."'
git_init_commit "$EXT"

# --- add_source discovers Claude-format skills with no staff.json ----------

run "$STAFF" add_source extrepo "$EXT"
assert_ok "add_source ingests a repo with no staff.json"
assert_symlink_resolves "repo link resolves" "$SB/repo/sources/extrepo/repo"
assert_file "source metadata written" "$SB/repo/sources/extrepo/source.toml"
assert_symlink_resolves "discovered skill installed" "$HOME/.claude/skills/alpha-skill"
# The whole point: a skill's supporting files must be reachable from the
# installed location, not merely present back in the source repo.
assert_skill_file_reachable "its reference file is reachable" \
  "$HOME/.claude/skills/alpha-skill" "reference/guide.md"
assert_skill_file_reachable "its script is reachable" \
  "$HOME/.claude/skills/alpha-skill" "scripts/run.sh"

# A description whose plain scalar ends in a quote must survive synthesis.
run "$STAFF" list
assert_output_contains "synthesized description is intact" 'Says "hello there."'

# --- the source repo is never written to -----------------------------------

assert_eq "external repo left untouched" "" "$(git -C "$EXT" status --porcelain)"

# --- re-adding points at the lifecycle commands instead of dead-ending -----

run "$STAFF" add_source extrepo "$EXT"
assert_fails "re-adding an existing bundle fails"
assert_output_contains "re-add suggests update_source" "staff update_source extrepo"

# --- drift: foreign-format discovery runs only at add/update time ----------

mkdir -p "$EXT/skills/gamma-skill/reference"
printf -- '---\nname: gamma-skill\ndescription: Does gamma things.\n---\n' \
  > "$EXT/skills/gamma-skill/SKILL.md"
printf 'guide for gamma-skill\n' > "$EXT/skills/gamma-skill/reference/guide.md"
rm -rf "$EXT/skills/beta-skill"
printf -- '---\nname: alpha-skill\ndescription: Revised alpha.\n---\n' \
  > "$EXT/skills/alpha-skill/SKILL.md"
git_init_commit "$EXT" drift

run "$STAFF" list --sourced true
assert_eq "a plain list does not re-synthesize foreign manifests" "2" \
  "$(printf '%s\n' "$LAST_OUTPUT" | grep -c 'markdown')"

# --- doctor notices the drift ----------------------------------------------

run "$STAFF" doctor
assert_output_contains "doctor flags the moved upstream" "staff update_source extrepo"

# --- update_source reconciles ----------------------------------------------

run "$STAFF" update_source extrepo
assert_ok "update_source succeeds"
assert_output_contains "reports the addition" "gamma-skill"
assert_output_contains "reports the removal" "beta-skill"

assert_symlink_resolves "added skill installed" "$HOME/.claude/skills/gamma-skill"
assert_skill_file_reachable "the added skill brings its files" \
  "$HOME/.claude/skills/gamma-skill" "reference/guide.md"
assert_no_file "dropped skill uninstalled" "$HOME/.claude/skills/beta-skill"
run "$STAFF" list --sourced true
assert_output_contains "edited description re-derived" "Revised alpha."
assert_eq "the discovered set reflects the update" "2" \
  "$(printf '%s\n' "$LAST_OUTPUT" | grep -c 'markdown')"

run "$STAFF" update_source extrepo
assert_ok "a second update is a no-op"
assert_output_contains "no-op reported plainly" "No projects added or removed"

# --- remove_source ----------------------------------------------------------

run "$STAFF" remove_source extrepo
assert_ok "remove_source succeeds"
assert_no_file "bundle directory removed" "$SB/repo/sources/extrepo"
assert_no_file "its skills uninstalled" "$HOME/.claude/skills/alpha-skill"
assert_eq "tracking cleared" "0" "$(jq '.installations | length' "$HOME/.staff/installed.json")"
assert_eq "external repo still untouched" "" "$(git -C "$EXT" status --porcelain)"
assert_file "external repo still exists" "$EXT/skills/alpha-skill/SKILL.md"

run "$STAFF" add_source extrepo "$EXT"
assert_ok "the same source can be added again after removal"

# --- error paths ------------------------------------------------------------

run "$STAFF" update_source no-such-source
assert_fails "update_source on an unknown bundle fails"
run "$STAFF" remove_source no-such-source
assert_fails "remove_source on an unknown bundle fails"
run "$STAFF" add_source only-one-arg
assert_fails "add_source without a path fails"

sandbox_cleanup
