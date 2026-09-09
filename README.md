# Autonomous Self-Healing Kubernetes

An AIOps-powered Kubernetes platform that detects application
failures and automatically triggers an Argo CD rollback when
application health crosses predefined thresholds.

## Architecture

Application
    ↓
Prometheus
    ↓
AlertManager
    ↓
AIOps Controller
    ↓
Incident Analysis
    ↓
Argo CD
    ↓
Rollback
    ↓
Previous Healthy Version

## Technology Stack

- Kubernetes
- Docker
- Argo CD
- Prometheus
- Grafana
- Loki
- AlertManager
- Python
- FastAPI
- GitHub Actions
- Helm

## Project Status

- [x] Initial repository
- [x] FastAPI application
- [x] Prometheus metrics
- [x] Docker container
- [ ] Kubernetes deployment
- [ ] Argo CD
- [ ] Prometheus
- [ ] Grafana
- [ ] AlertManager
- [ ] AIOps controller
- [ ] Automated rollback
- [ ] Failure injection
- [ ] CI/CD