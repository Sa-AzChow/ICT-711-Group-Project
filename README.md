ICT-711 Group Project - EcoGrid Energy

EcoGrid Energy is a peer-to-peer renewable energy trading prototype for ICT711 Advanced Software Engineering. The project demonstrates how smart meter readings can be ingested, transformed into energy positions, matched in a marketplace, and settled through a resilient event-driven workflow.

## Project Overview

The prototype supports the main architecture described in the team report:

- Meter ingestion and validation
- Energy surplus / deficit calculation
- Event-driven marketplace matching
- Trade settlement workflow
- Saga compensation for failed settlement
- Idempotency checks to prevent duplicate settlement
- Fitness-function tests for performance, reliability, security, and maintainability

## Tech Stack

- Python
- Python `unittest`
- In-memory event broker simulation
- Domain-Driven Design concepts
- Event-Driven Architecture concepts
- Saga pattern for distributed transaction handling

## Repository Structure

```text
.
├── __init__.py                     # Package marker for the EcoGrid prototype
├── broker.py                       # In-memory event broker and broker bridge
├── models.py                       # Domain events and data models
├── resilience.py                   # Retry and circuit breaker utilities
├── services.py                     # Meter ingestion, marketplace, settlement, and system orchestration
├── test_functional_requirements.py # Functional requirement tests
├── test_fitness_functions.py       # Architecture fitness-function tests
└── README.md
```

## Setup

Clone the repository:

```bash
git clone https://github.com/Sa-AzChow/ICT-711-Group-Project.git ecogrid
```

Move to the parent folder of the cloned package:

```bash
cd ..
```

Create a virtual environment:

```bash
python -m venv .venv
```

Activate the virtual environment:

```bash
# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate
```

No external dependencies are required for the current prototype. It uses the Python standard library.

## How to Run Tests

## Run the demo

```powershell
python run_demo.py
```

## Run tests (fitness checks)

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

## Team Contributions

| Member | Primary Contribution Area |
|---|---|
| Himakesh Chakilam | Meter ingestion and validation design |
| Bhramarambika | Marketplace matching and domain model |
| Udaya | Settlement Saga and compensation logic |
| Sabrina | CI/CD quality gates, observability, and report coordination |

## Assessment Alignment

This prototype supports the ICT711 architecture report by demonstrating:

- Domain-Driven Design bounded contexts
- Microservices-style separation of responsibilities
- Event-Driven Architecture using an in-memory broker
- Saga-based distributed transaction handling
- Resilience patterns such as retry, circuit breaker, and idempotency
- Automated functional and architecture fitness-function tests

*code output is in output folder*
