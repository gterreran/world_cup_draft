# Deployment Guide

This document describes how the World Cup Draft application is deployed and maintained in production.

---

# Architecture

The application currently runs on:

* Railway (application hosting)
* Railway PostgreSQL
* Django
* Gunicorn
* WhiteNoise

Current deployment flow:

GitHub → Railway → PostgreSQL

The production application is deployed from the `main` branch.

---

# Branch Strategy

The repository uses the following branching model:

* `main`

  * Stable and deployable
  * Production deployments originate from this branch

* `dev`

  * Integration branch
  * Features are merged here before production

* `feature/*`

  * Individual features
  * Examples:

    * `feature/railway-deployment`
    * `feature/live-draft`
    * `feature/score-ingestion`

---

# PostgreSQL Migration

The project originally used SQLite and was migrated to PostgreSQL before deployment.

## Install PostgreSQL

```bash
brew install postgresql@17
brew services start postgresql@17
```

Homebrew automatically created a PostgreSQL superuser role matching the macOS username:

```text
gterreran
```

This role was used for administrative tasks.

## Create Application User

Connect as the PostgreSQL superuser:

```bash
psql postgres
```

Create a dedicated application user:

```sql
CREATE USER worldcup
    WITH PASSWORD '<password>';
```

## Create Database

```sql
CREATE DATABASE worldcup_draft
    OWNER worldcup;

GRANT ALL PRIVILEGES ON DATABASE worldcup_draft
    TO worldcup;
```

## Fix Schema Permissions

After database creation, Django migrations failed with:

```text
permission denied for schema public
```

The following commands resolved the issue:

```sql
\c worldcup_draft

GRANT USAGE, CREATE ON SCHEMA public TO worldcup;

ALTER SCHEMA public OWNER TO worldcup;
```

## Configure Django

Example local connection string:

```text
postgresql://worldcup:<password>@localhost:5432/worldcup_draft
```

Store this in:

```text
DATABASE_URL
```

## Run Migrations

```bash
python manage.py migrate
```

Verify:

```bash
python manage.py shell
```

```python
from django.db import connection
print(connection.settings_dict["ENGINE"])
```

Expected output:

```text
django.db.backends.postgresql
```

---

# Railway Setup

## Railway Project

Project:

```text
world-cup-draft
```

Services:

```text
world_cup_draft
Postgres
```

---

# Railway Variables

Required application variables:

```text
DEBUG=False
SECRET_KEY=<production secret>
DATABASE_URL=${{Postgres.DATABASE_URL}}
```

The SECRET_KEY can be generated using:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

The application must also specify:

```text
ALLOWED_HOSTS=<railway domain>.up.railway.app
CSRF_TRUSTED_ORIGINS=https://<railway domain>.up.railway.app
```

The deployed application must use:

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
```

This uses Railway internal networking and avoids egress charges.

Do NOT use:

```text
Postgres.DATABASE_PUBLIC_URL
```

for the deployed application.

---

# Public Domain

Once the application is deployed, Railway provides a public domain

```text
<railway domain>.up.railway.app
```

However this needs to be manually generated.

---

# Railway CLI

In order to run commands locally that connect to the production database, the Railway CLI is required.

Install:

```bash
bash <(curl -fsSL railway.com/install.sh)
```

To login to your Railway account:

```bash
railway login
```

which opens a browser window for authentication.

Then we can link the project:

```bash
railway link
```

which prompts to select the project.

## Railway shell and Production Database Access

Opening up a shell allows to run commands in the production environment. To open a shell:

```bash
railway shell
```

N.B. This doesn not ssh into the production environment, but rather sets up the local environment to connect to the production database. This means that the environment variables are available locally, but the code is still executed locally. If in your local machine you are using a conda environment, you will have to activate it again in the railway shell.

To connect to the production database, we must use the public URL provided by Railway. This is available in the environment variable:

```text
Postgres.DATABASE_PUBLIC_URL
```

from Railway. Copy this value from the Railway dashboard and set it to the local environment variable:

```bash
export DATABASE_URL="<public postgres url>"
```

This allows local Django commands to operate on the production database. For example, we can create a superuser in the production database, run migrations, backup data, or run any other management command that requires database access.

Examples:

```bash
python manage.py createsuperuser
python manage.py migrate
python manage.py import_tournament_teams tournaments/data/world_cup_2026_teams.json
python manage.py dumpdata \
    --natural-foreign \
    --natural-primary \
    > backup.json
```

---

# Deployment Procedure

Deployments are performed automatically by Railway after pushing to GitHub.

Typical process:

```bash
git checkout dev
git pull

git checkout -b feature/my-feature
```

Develop feature.

Merge:

```bash
feature/my-feature
    ↓
dev
```

Test.

Promote:

```bash
dev
    ↓
main
```

Push:

```bash
git push origin main
```

Railway automatically deploys.

---

# Verifying a Deployment

After deployment:

1. Open home page
2. Open login page
3. Log into admin
4. Create a test object
5. Verify database persistence
6. Verify static files load correctly

Useful URLs:

```text
/
```

```text
/league/
```

```text
/admin/
```

# Common Problems

## Railway build fails installing Python

Observed error:

```text
No GitHub artifact attestations found
```

Fix:

```text
MISE_PYTHON_GITHUB_ATTESTATIONS=false
```

Railway environment variable.

---

## Django cannot connect to production database

Verify:

```bash
echo $DATABASE_URL
```

Verify that:

```text
DATABASE_URL
```

points to:

```text
Postgres.DATABASE_URL
```

inside Railway.

---

## DisallowedHost

Add:

```text
ALLOWED_HOSTS
```

and

```text
CSRF_TRUSTED_ORIGINS
```

for the Railway domain.

---

# Future Improvements

Planned future infrastructure work:

* Staging environment
* Redis
* Background workers
* Scheduled score ingestion
* Live draft synchronization
* WebSockets
* Automated backups
* Monitoring and error reporting
