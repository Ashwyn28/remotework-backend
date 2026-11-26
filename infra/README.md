# orbbits job on AWS (serverless)

```
            jobs.orbbits.io (Route 53)
                      │
                CloudFront (HTTPS, security headers)
     ┌────────────────┼─────────────────┬──────────────────────┐
  /* (app)       /data/*            /static/*               /api/*
  S3 site        S3 data:           S3 data:                Lambda "api" (function URL,
  bucket         board.json         company logos           only callable with CloudFront's
                      ▲                  ▲                  secret header) ──► DynamoDB "users"
                      └──── Lambda "sync" ┘
                            daily 06:00 London (EventBridge Scheduler)
```

| Part | Code |
| --- | --- |
| Sync: careers sites → `data/board.json` + logos | `jobfeed/` (`sync_handler.py`) |
| Accounts API: Google sign-in, answers, saved roles | `jobapi/` (`lambda_handler.py`) |
| Site | the `remotework` repo, built as static files |
| Infrastructure | `infra/terraform/` |

Expected cost at low traffic: well under $1/month (CloudFront, Lambda and DynamoDB free
allowances), plus the existing Route 53 zone.

## Deploy

```sh
infra/deploy.sh          # package, terraform apply (asks first), first sync, upload site
infra/deploy.sh site     # frontend only
```

After the first deploy, add `https://jobs.orbbits.io` to the Google OAuth client's
**Authorised JavaScript origins**, or the sign-in button will not load.

### Chat agent (`/api/agent/`)

The `/agent` page talks to Claude Haiku 5.5 through the `orbbits-job-agent` Lambda. The browser
holds the conversation and runs the search tools; the Lambda fixes the model, prompt, tools and
output cap (`jobagent/prompt.py`) and checks daily limits before each call
(`agent_limit_per_ip_per_day`, `agent_limit_site_per_day`). If the endpoint fails or a limit is
hit, the page falls back to its rule-based search.

There is no Anthropic API key in AWS. The agent's role gets short-lived tokens from AWS STS
(outbound web identity federation) and Anthropic accepts them under a federation rule that
trusts only that role. One-time setup:

1. Enable outbound federation on the account and note the issuer URL:
   `aws iam enable-outbound-web-identity-federation` then
   `aws iam get-outbound-web-identity-federation-info`
2. Claude Console > Settings > Keys > Workload identity > Connect workload > AWS: paste the
   issuer URL; rule subject `arn:aws:iam::<account>:role/orbbits-job-agent` (the
   `agent_role_arn` output), audience `https://api.anthropic.com`; target a service account.
3. Put the organization id, rule id (and service account / workspace ids if needed) in
   `infra/terraform/terraform.tfvars` as `anthropic_*` variables, then apply.

## Develop locally

```sh
python -m jobfeed sync --out .local/site-data        # build board.json and logos
python -m jobapi.devserver --data .local/site-data   # /api, /data and /static on :8787
cd ../remotework && npx svelte-kit dev --port 3001   # proxies those paths to :8787
```

The dev server also serves `/api/agent/`, calling Claude with this machine's
`ANTHROPIC_API_KEY`. Pass `--site-origin` to match the frontend's port (default
`http://localhost:3001`). Without a key the agent page falls back to rule-based search.

## Tests

```sh
python -m unittest discover -s jobfeed/tests -t .
python -m unittest discover -s jobapi/tests -t .
python -m unittest discover -s jobagent/tests -t .
```

## Operations

- Run a sync now: `aws lambda invoke --function-name orbbits-job-sync /dev/stdout`
- Roll back a bad board: restore the previous version of `data/board.json` in the data bucket
  (versions are kept for 30 days).
- Accounts table has deletion protection and point-in-time recovery (35 days).
- Logs: CloudWatch log groups `/aws/lambda/orbbits-job-*`, kept 14 days. The agent logs token
  counts per model call (`turn stop=… in=… cache_read=… out=…`).
- Terraform state is local (`infra/terraform/terraform.tfstate`) and contains the generated
  secrets. Keep it out of git; move it to an S3 backend before anyone else deploys.
