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

## Develop locally

```sh
python -m jobfeed sync --out .local/site-data        # build board.json and logos
python -m jobapi.devserver --data .local/site-data   # /api, /data and /static on :8787
cd ../remotework && npx svelte-kit dev --port 3001   # proxies those paths to :8787
```

## Tests

```sh
python -m unittest discover -s jobfeed/tests -t .
python -m unittest discover -s jobapi/tests -t .
```

## Operations

- Run a sync now: `aws lambda invoke --function-name orbbits-job-sync /dev/stdout`
- Roll back a bad board: restore the previous version of `data/board.json` in the data bucket
  (versions are kept for 30 days).
- Accounts table has deletion protection and point-in-time recovery (35 days).
- Logs: CloudWatch log groups `/aws/lambda/orbbits-job-*`, kept 14 days.
- Terraform state is local (`infra/terraform/terraform.tfstate`) and contains the generated
  secrets. Keep it out of git; move it to an S3 backend before anyone else deploys.
