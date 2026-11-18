#!/usr/bin/env bash
# Deploy orbbits job: package the Lambdas, apply Terraform, upload the site, run the first sync.
#
#   infra/deploy.sh            everything (Terraform shows its plan and asks before changing AWS)
#   infra/deploy.sh site       only rebuild and upload the frontend
#
# Needs: AWS credentials, Terraform, Python 3, Node. The frontend repo is expected beside this one
# (../remotework) unless FRONTEND_DIR is set.
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="${FRONTEND_DIR:-$BACKEND_DIR/../remotework}"
TF_DIR="$BACKEND_DIR/infra/terraform"
PYTHON="${PYTHON:-python3}"

tf_output() { terraform -chdir="$TF_DIR" output -raw "$1"; }

deploy_infra() {
  echo "==> Packaging Lambdas"
  "$PYTHON" "$BACKEND_DIR/infra/package.py"
  echo "==> Applying Terraform (review the plan before answering yes)"
  terraform -chdir="$TF_DIR" init -input=false >/dev/null
  terraform -chdir="$TF_DIR" apply
}

deploy_site() {
  local bucket distribution
  bucket="$(tf_output site_bucket)"
  distribution="$(tf_output distribution_id)"

  echo "==> Building the site"
  (cd "$FRONTEND_DIR" && npm ci && npm run build)

  echo "==> Uploading to s3://$bucket"
  # hashed asset files never change, so browsers may keep them for a year
  aws s3 sync "$FRONTEND_DIR/build/_app/immutable" "s3://$bucket/_app/immutable" \
    --cache-control "public, max-age=31536000, immutable"
  # everything else (the app shell above all) is checked on every visit
  aws s3 sync "$FRONTEND_DIR/build" "s3://$bucket" --delete \
    --exclude "_app/immutable/*" --cache-control "no-cache"

  echo "==> Refreshing CloudFront"
  aws cloudfront create-invalidation --distribution-id "$distribution" --paths "/*" >/dev/null
}

first_sync() {
  local data_bucket function
  data_bucket="$(tf_output data_bucket)"
  function="$(tf_output sync_function)"
  if aws s3api head-object --bucket "$data_bucket" --key data/board.json >/dev/null 2>&1; then
    return
  fi
  echo "==> Running the first sync (about a minute)"
  aws lambda invoke --function-name "$function" --cli-read-timeout 330 /dev/stdout
  echo
}

case "${1:-all}" in
  site) deploy_site ;;
  all)
    deploy_infra
    first_sync
    deploy_site
    echo "==> Live at $(tf_output site_url)"
    ;;
  *) echo "usage: $0 [all|site]" >&2; exit 2 ;;
esac
