#!/usr/bin/env bash
# The ledger (nishpaksh/ledger.py): after the desk, write this run's record into ledger/ (embedding use, outlet yield,
# the express lane's funnel) and commit ONLY that folder to the branch the job runs on, so the next zip of the
# repository carries the numbers. Same shape as learn_titles.sh: a push by the job's own token starts no other
# workflow; if the push is refused the step fails harmlessly (continue-on-error): nothing depends on it.
set -euo pipefail
BRANCH="${GITHUB_REF_NAME:-main}"
REMOTE="${LEDGER_REMOTE:-https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git}"
DIR="ledger"
GIT=(git -c user.name="nishpaksh-ledger" -c user.email="41898282+github-actions[bot]@users.noreply.github.com")
# start from the branch as it is now (another job may have pushed since this one started)
"${GIT[@]}" pull --quiet --rebase --autostash "$REMOTE" "$BRANCH" || echo "could not update the branch; writing on the checkout"
python -m nishpaksh.ledger --dir "$DIR"
if git diff --quiet -- "$DIR" && [ -z "$(git ls-files --others --exclude-standard -- "$DIR")" ]; then
  echo "ledger: nothing new"
  exit 0
fi
git add "$DIR"
"${GIT[@]}" commit --quiet -m "Ledger $(date -u '+%Y-%m-%d %H:%M')"
git push --quiet "$REMOTE" "HEAD:${BRANCH}" || {
  "${GIT[@]}" pull --quiet --rebase "$REMOTE" "$BRANCH"
  git push --quiet "$REMOTE" "HEAD:${BRANCH}"
}
echo "ledger pushed"
