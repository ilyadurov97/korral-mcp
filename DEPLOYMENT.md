# Deployment

The MCP server ships as a container that runs entirely inside Korral's GCP
tenancy. No StoreLink data crosses into anything Duvo- or public-internet-hosted.
The pipeline (build, push, deploy) is owned and run by Korral.

## Architecture

- **Compute**: Cloud Run service, `--ingress=internal` (reachable only from
  inside Korral's VPC / via Serverless VPC Access — never from the public
  internet).
- **Network path to StoreLink**: a Serverless VPC Connector attached to the
  Cloud Run service, routed into the VPC where StoreLink lives.
- **Image**: Google Artifact Registry, Docker format, in-region.
- **Secrets**: Google Secret Manager holds the store-key map in production.
  Locally, the same code path reads `keys.json` (see below) — no code
  branches between environments, only which credential source is configured.
  The Secret Manager client (`google-cloud-secret-manager`) is a production-only
  dependency, so it's kept out of `requirements.txt` (the dev/test set) and
  installed by the Dockerfile into the image instead. `key_manager.py` imports
  it lazily, so local dev and tests never need it.
- **Transport**: `mcp.run(transport="streamable-http")` on `$PORT` in
  production; `stdio` locally, for when the Duvo agent runtime spawns the
  server as a subprocess during development. Controlled by `MCP_TRANSPORT`.

## Environments

| | Dev | Production |
|---|---|---|
| Keys | `keys.json` (`STORELINK_KEYS_FILE`) | Secret Manager (`STORELINK_KEYS_SECRET_NAME`) |
| Transport | `stdio` (default) | `streamable-http` (set by the image's `ENV`) |
| Where it runs | Engineer's machine / `docker run` | Cloud Run, internal ingress only |

`key_manager.py` picks Secret Manager over the JSON file automatically
whenever `STORELINK_KEYS_SECRET_NAME` is set — that's the only switch. It
re-reads the source every 5 minutes (`STORELINK_KEYS_CACHE_TTL`) so a weekly
key rotation in Secret Manager doesn't require a redeploy.

## One-time setup

```bash
export PROJECT_ID=korral-prod
export REGION=europe-west1
export REPO=korral-mcp
export SERVICE=korral-storelink-mcp
export VPC_CONNECTOR=korral-private-connector   # already routed to StoreLink's subnet

gcloud artifacts repositories create $REPO \
  --repository-format=docker --location=$REGION --project=$PROJECT_ID

# Secret holding the same {store_id: key} JSON shape as keys.json
gcloud secrets create storelink-keys --project=$PROJECT_ID
gcloud secrets versions add storelink-keys --data-file=prod-keys.json --project=$PROJECT_ID

# Cloud Run's runtime service account needs read access to that secret only
gcloud secrets add-iam-policy-binding storelink-keys \
  --member="serviceAccount:$SERVICE@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" --project=$PROJECT_ID
```

## Routine release (build → push → deploy)

```bash
TAG=$(git rev-parse --short HEAD)
IMAGE=$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/storelink-mcp:$TAG

docker build -t $IMAGE .
docker push $IMAGE

gcloud run deploy $SERVICE \
  --image=$IMAGE \
  --region=$REGION \
  --no-allow-unauthenticated \
  --ingress=internal \
  --vpc-connector=$VPC_CONNECTOR \
  --vpc-egress=private-ranges-only \
  --set-env-vars=STORELINK_API_URL=https://storelink.internal.korral.example/v1,STORELINK_KEYS_SECRET_NAME=projects/$PROJECT_ID/secrets/storelink-keys/versions/latest
```

Cloud Run only shifts traffic to the new revision once it passes its startup
health check; the previous revision keeps serving until then, so this is
zero-downtime by default as long as the new revision comes up healthy.

## If something breaks: standard rollback

```bash
# Find the last known-good revision
gcloud run revisions list --service=$SERVICE --region=$REGION

# Send 100% of traffic back to it immediately — no rebuild needed
gcloud run services update-traffic $SERVICE --region=$REGION \
  --to-revisions=$SERVICE-00042-abc=100
```

To roll forward again after a fix, repeat the routine release sequence above
with a new `TAG`. Never edit a running revision in place — always ship a new
image and let Cloud Run's revision model handle the cutover.

## Day-1 checklist (verify with Korral IT before go-live)

- [ ] Cloud Run service resolves and reaches StoreLink's internal hostname
      over the VPC connector (test with a one-off `gcloud run jobs execute`
      or a shell in the same VPC — not from a laptop).
- [ ] Firewall rules permit the VPC connector's range → StoreLink's subnet
      on the StoreLink API port.
- [ ] Cloud Run `--ingress=internal` confirmed — no public URL responds.
- [ ] Runtime service account has `roles/secretmanager.secretAccessor` on
      `storelink-keys` only (not project-wide Secret Manager access).
- [ ] `prod-keys.json` uploaded to Secret Manager matches Korral IT's current
      weekly rotation, and IT knows to push new versions there (not to a
      file) going forward.
- [ ] Artifact Registry repo has vulnerability scanning enabled.
- [ ] Korral IT (not Duvo) holds deploy/rollback access to this Cloud Run
      service and the Artifact Registry repo.
- [ ] Log/decision output (`logs/decisions.log`, `logs/debug.jsonl`) lands
      somewhere Korral can audit — confirm the mount or log sink before
      relying on it, since Cloud Run's local filesystem is ephemeral per
      instance.
- [ ] Confirm no StoreLink response data appears in Cloud Logging beyond
      what `observability.py` intentionally logs.
