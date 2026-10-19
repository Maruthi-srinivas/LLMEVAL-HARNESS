# Operations

These steps use Docker Compose only. Do not install Node, Python, PostgreSQL, Redis, or kubectl on the host.

## Identity

Password registration stays available. The Compose service `oidc` is a fixture OpenID Connect provider used for local login. A real provider is not started. Set these variables only when you point the API at one:

- `OIDC_ISSUER`
- `OIDC_CLIENT_ID`
- `OIDC_CLIENT_SECRET`

Leave them unset in the free deployment. The fixture default secret is `fixture-secret` and must not be reused for a real provider.

## Secrets

Secrets are environment variables passed into containers. They are not baked into images. To rotate them, change the value in the server `.env` file and recreate the containers:

- `SECRET_KEY` signs JWTs. After it changes, existing sessions must log in again.
- `POSTGRES_PASSWORD` and `DATABASE_URL` must be changed together, then `docker compose up -d postgres api worker`.
- `ARTIFACT_S3_SECRET_KEY` and the MinIO root password must be changed together, then recreate `minio`, `api`, and `worker`.

## Workers

One worker container is enough for the mock workload. Add another on the same machine with:

```bash
docker compose up -d --scale worker=2
```

## Retention and backups

An owner sets `retention_days` for a workspace. The `retention` container deletes finished runs older than that period, their traces, and the matching MinIO report object. `pg_dump` files under the backups prefix still expire after 14 days. Old dump files are not rewritten.

## Restore

```bash
docker compose --profile backup run --rm backup
docker compose --profile backup run --rm backup-upload
docker compose --profile restore up -d postgres-restore
docker compose --profile restore run --rm restore-apply
```

`restore-apply` loads the newest plain SQL dump into the second Postgres container. Read a known run from that database with `DATABASE_URL=postgresql+psycopg://evalforge:evalforge@postgres-restore:5432/restored`.

## Rollback

Record the running image digest in `releases.log`. Tag it `evalharness-app:staging-previous`. Start staging with that tag:

```bash
docker tag evalharness-app:latest evalharness-app:staging-previous
docker compose -f docker-compose.staging.yml up -d
```

Staging listens on port 8010 and uses the same Postgres and Redis containers. Confirm `http://localhost:8010/health`.

## Load

The stated workload is five mock runs at once, one workspace each:

```bash
docker compose run --rm api python -m evaluator.loadtest
```

The drill fails if a run does not finish or a case is stored twice.
