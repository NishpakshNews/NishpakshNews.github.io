#!/usr/bin/env bash
# One job script for the three learners (nishpaksh/learning.py; Oct 16 2026, replacing learn_titles.sh and
# learn_synonyms.sh): run the learner, then commit its files (config/ only: words, pairs and counts, never article
# text) to the branch the job runs on. The learner's memory itself lives in the newsroom (learn_candidates), saved
# with it. A push by the job's own token starts no other workflow. If the push is refused, the step fails harmlessly
# (continue-on-error): nothing else depends on it.
#   bash .github/scripts/learn.sh <name> <python module> <file> [<file> ...]
set -euo pipefail
NAME="$1"; MODULE="$2"; shift 2
FILES=("$@")
BRANCH="${GITHUB_REF_NAME:-main}"
REMOTE="${LEARN_REMOTE:-https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git}"
WHO=(-c user.name="nishpaksh-${NAME}" -c user.email="41898282+github-actions[bot]@users.noreply.github.com")
# start from the branch as it is now (the owner may have approved or struck out an entry since this job started)
git "${WHO[@]}" pull --quiet --rebase --autostash "$REMOTE" "$BRANCH" || echo "could not update the branch; learning on the checkout"
python -m "$MODULE"
changed=0
for f in "${FILES[@]}"; do
  if ! git diff --quiet -- "$f" || [ -n "$(git ls-files --others --exclude-standard -- "$f")" ]; then changed=1; fi
done
if [ "$changed" = 0 ]; then echo "no change in ${NAME}"; exit 0; fi
git add "${FILES[@]}"
git "${WHO[@]}" commit --quiet -m "Learned ${NAME} $(date -u '+%Y-%m-%d %H:%M')"
git push --quiet "$REMOTE" "HEAD:${BRANCH}" || {
  git "${WHO[@]}" pull --quiet --rebase "$REMOTE" "$BRANCH"
  git push --quiet "$REMOTE" "HEAD:${BRANCH}"
}
echo "${NAME} pushed"
