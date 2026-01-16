# Inter-Replica Communication on DigitalOcean App Platform

A demonstration of how service replicas can discover and communicate with each other on serverless container platforms.

## The Challenge

Serverless container platforms like **DigitalOcean App Platform**, **AWS Fargate**, and **Google Cloud Run** treat containers as interchangeable "cattle" using Kubernetes **Deployments** (not StatefulSets). This means:

- No stable network identity (`pod-0`, `pod-1` DNS names don't exist)
- No headless service (DNS returns a single load-balanced IP, not individual pod IPs)
- Pod IPs change on every restart

For stateless services, this is perfect. But **stateful clustered services** (Vault, Keycloak, etcd) that need peer-to-peer communication face a discovery problem: *How does Pod A find Pod B?*

---

## Demo Application

This repository contains a FastAPI application that demonstrates inter-replica communication.

### What It Shows

- Current replica's hostname and IP address
- Discovered peer replicas via subnet scanning
- Cluster status (found vs expected replicas)
- Auto-refreshes every 5 seconds to show load balancer rotation

### Live Demo

**URL**: https://replica-comm-demo-ty4kj.ondigitalocean.app

Refresh multiple times to see different hostnames as the load balancer rotates between replicas.

### Important Limitation

> **This code is for demonstration purposes only.**
>
> The subnet scanning approach discovers ALL services listening on port 8080 in the same app. If you have multiple service components (web, api, worker) all on port 8080, they will ALL be discovered—not just replicas of your specific service.
>
> **For production use, see the recommended patterns below.**

---

## Production Recommendations

Since serverless platforms use Kubernetes Deployments (not StatefulSets), peer discovery must happen at the **application level**. The infrastructure won't help you.

### 1. Keycloak: JDBC_PING (Database-Based Discovery)

Keycloak's JGroups clustering supports `JDBC_PING`—replicas register their IPs in a shared database table and discover peers by querying it.

```yaml
# app.yaml
services:
  - name: keycloak
    image:
      registry: docker.io
      repository: quay.io/keycloak/keycloak
      tag: latest
    instance_count: 3
    envs:
      - key: KC_DB
        value: postgres
      - key: KC_DB_URL
        value: ${db.JDBC_DATABASE_URL}
      - key: KC_CACHE
        value: ispn
      - key: KC_CACHE_STACK
        value: jdbc-ping

databases:
  - name: db
    engine: PG
```

**How it works**: Each replica writes its IP to a `JGROUPSPING` table. Replicas query this table to find peers, then establish direct TCP connections.

### 2. Vault: PostgreSQL Backend (Eliminate Peer Discovery)

Vault's Raft consensus requires stable network identities—problematic on serverless platforms. The production solution is to **offload state to a managed database**.

```yaml
services:
  - name: vault
    image:
      registry: docker.io
      repository: hashicorp/vault
      tag: latest
    instance_count: 3
    envs:
      - key: VAULT_LOCAL_CONFIG
        value: |
          storage "postgresql" {
            connection_url = "${db.DATABASE_URL}"
            ha_enabled = true
          }
          listener "tcp" {
            address = "0.0.0.0:8200"
            tls_disable = true
          }

databases:
  - name: db
    engine: PG
```

**How it works**: Vault becomes stateless—the database handles locking and HA. No peer discovery needed.

### 3. Custom Applications: Central Registry Pattern

If your application doesn't have built-in discovery (like JDBC_PING), implement a **central registry** pattern:

1. **On startup**: Register `(service_name, instance_id, private_ip)` in a shared database or Redis
2. **For discovery**: Query the registry for all instances of your service
3. **On shutdown**: Deregister (or use TTL-based expiration)

```python
# Pseudocode
def register_self(db, service_name, instance_id, private_ip):
    db.execute("""
        INSERT INTO service_registry (service, instance, ip, last_seen)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (service, instance) DO UPDATE SET ip = %s, last_seen = NOW()
    """, (service_name, instance_id, private_ip, private_ip))

def discover_peers(db, service_name):
    return db.query("""
        SELECT ip FROM service_registry
        WHERE service = %s AND last_seen > NOW() - INTERVAL '30 seconds'
    """, (service_name,))
```

**Why not the subnet scanning demo?** It discovers ALL services on port 8080, not just your service's replicas. The central registry approach is precise.

---

## Why This Matters

| Platform | Underlying Model | Peer Discovery |
|----------|------------------|----------------|
| Kubernetes StatefulSet | Pets (stable identity) | DNS-based (`pod-0.svc`) |
| App Platform / Fargate / Cloud Run | Cattle (ephemeral) | Application-level required |

The "90% rule" in production: **Don't cluster the containers; cluster the data.** Move state to managed databases (PostgreSQL, Redis) and keep containers stateless.

---

## Technical Details

### What We Verified

| Discovery Method | Works? | Notes |
|------------------|--------|-------|
| `doctl apps list-instances` | Partial | Returns instance names, but NOT private IPs |
| DNS resolution of instance names | No | No headless service in App Platform |
| Subnet scanning | Yes | Finds all services on the port (not just your replicas) |
| Service DNS (`main-service`) | Yes | Returns single ClusterIP (round-robin load balancer) |

### API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | HTML UI showing replica info and cluster status |
| `GET /health` | Health check (returns hostname, IP) |
| `GET /identity` | JSON identity of this replica |
| `GET /peers` | JSON list of discovered peers |

---

## Deployment

### Deploy to App Platform

```bash
doctl apps create --spec .do/app.yaml
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVICE_NAME` | main-service | Service identifier |
| `REPLICA_COUNT` | 3 | Expected number of replicas |
| `PORT` | 8080 | HTTP listen port |

---

## Files

| File | Description |
|------|-------------|
| `main.py` | FastAPI demo application |
| `requirements.txt` | Python dependencies |
| `.do/app.yaml` | App Platform deployment spec |
| `README.md` | This documentation |

---

## Conclusion

**Serverless container platforms can run stateful clustered services**, but peer discovery must be handled at the application level:

1. **Use built-in mechanisms** (JDBC_PING for Keycloak)
2. **Offload state to managed databases** (PostgreSQL for Vault)
3. **Implement a central registry** (for custom applications)

For workloads requiring true Kubernetes StatefulSet semantics (etcd, ZooKeeper, Kafka), use **DigitalOcean Kubernetes (DOKS)** instead of App Platform.
