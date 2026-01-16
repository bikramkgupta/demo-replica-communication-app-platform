# Replica Communication Demo for DigitalOcean App Platform

This application demonstrates how multiple replicas of a service can discover and communicate with each other on DigitalOcean App Platform.

## The Challenge

Unlike Kubernetes StatefulSets, App Platform doesn't provide stable DNS names like `pod-0.service`, `pod-1.service`. This demo shows how to work around this limitation using **subnet scanning** for peer discovery.

## Features

- Shows current replica hostname and IP address
- Automatically discovers peer replicas via network scanning
- Displays cluster status with found vs. expected replicas
- Auto-refreshes every 5 seconds to show load balancer rotation
- Clean, modern UI

## How It Works

1. **Discovery**: Each replica scans its local subnet for other pods listening on the service port
2. **Communication**: Replicas communicate directly via IP addresses
3. **Load Balancing**: The service DNS name (`main-service`) provides round-robin load balancing

## Deployment

### One-Click Deploy

[![Deploy to DO](https://www.deploytodo.com/do-btn-blue.svg)](https://cloud.digitalocean.com/apps/new?repo=https://github.com/bikramkgupta/demo-replica-communication-app-platform/tree/main)

### Manual Deploy

```bash
doctl apps create --spec .do/app.yaml
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVICE_NAME` | main-service | Name of the service |
| `REPLICA_COUNT` | 3 | Expected number of replicas |
| `PORT` | 8080 | HTTP port to listen on |

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Main UI showing replica info and cluster status |
| `GET /health` | Health check (returns hostname, IP, timestamp) |
| `GET /identity` | JSON response with replica identity |
| `GET /peers` | JSON list of discovered peer replicas |

## Use Cases

This pattern is useful for:
- **Keycloak**: Session replication between replicas (use JDBC_PING instead)
- **Vault**: Cluster formation (better to use PostgreSQL backend)
- **Custom Apps**: Any application needing peer-to-peer communication

## Learn More

See [FINDINGS.md](./FINDINGS.md) for detailed analysis of inter-replica communication patterns on App Platform.
