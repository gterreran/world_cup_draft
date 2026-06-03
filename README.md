# World Cup Draft

World Cup Draft is a Django web application that turns an international football tournament into a fantasy draft experience.

Managers are assigned national teams, earn points based on tournament performance, and compete in league standings throughout the competition.

## Features

### League Management

* Create and manage leagues
* Commissioner controls
* League locking/unlocking
* Sleeper manager import

### Team Assignment

* Random team assignment with constraints
* Tier-aware assignment support
* Live draft presentation
* Assignment locking for league integrity

### Tournament Tracking

* Group stage standings
* Qualification status tracking
* Knockout bracket visualization
* FIFA-compliant third-place allocation

### Fantasy Scoring

* Configurable scoring system
* Configurable tiebreakers
* Live league standings
* Team contribution breakdowns

### Projections

* Maximum reachable points calculations
* Cached projection engine
* Projection freshness tracking

## Technology Stack

* Python
* Django
* PostgreSQL
* Vanilla JavaScript
* HTML/CSS

## Development Status

The application is actively developed and currently supports:

* League creation and management
* Sleeper manager imports
* Team assignment workflows
* Live draft presentation
* Tournament progression tracking
* Projection calculations

Planned future enhancements include:

* Public live draft pages
* Automatic score ingestion
* Background task processing
* Live tournament updates
* Probability and simulation tools

## Local Development

```bash
git clone <repository>
cd world-cup-draft

python -m venv venv
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Visit:

```
http://127.0.0.1:8000/
```

## License

Private project currently under active development.
