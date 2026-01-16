# Research Journey: Inter-Replica Communication on App Platform

This document tells the story of how we investigated whether DigitalOcean App Platform service replicas can discover and communicate with each other—a requirement for stateful clustered applications like Vault and Keycloak.

---

## The Starting Question

**Can replicas of a service on App Platform talk to each other?**

When running stateful services like HashiCorp Vault or Keycloak, replicas need to form a cluster. They need to discover each other and establish direct peer-to-peer connections. On Kubernetes with StatefulSets, this is straightforward—each pod gets a stable DNS name like `pod-0.service`, `pod-1.service`. But App Platform abstracts away the underlying Kubernetes. Would it still work?

---

## Phase 1: Setting Up the Experiment

We deployed a simple Python FastAPI service with 3 replicas on App Platform. The goal was to see what each replica could discover about its environment and its peers.

**First roadblock**: The smallest instance size (`apps-s-1vcpu-0.5gb`) only allows 1 replica. We had to upgrade to `apps-s-1vcpu-1gb` to get 3 replicas running.

With the app deployed, we could see three distinct instances in the DigitalOcean console:
- `main-service-768976868d-gtxdh`
- `main-service-768976868d-rq7kk`
- `main-service-768976868d-vprdj`

These names looked promising—they follow the Kubernetes pod naming pattern.

---

## Phase 2: Getting Inside the Containers

To investigate what's discoverable from inside the containers, we used the **DO App Sandbox SDK** (`do-app-sandbox` Python package). This SDK lets you connect to a running App Platform container and execute commands—essentially giving you shell access without `doctl apps console` (which requires interactive input).

```python
from do_app_sandbox import Sandbox

app = Sandbox.get_from_id(app_id="070a1449-ced3-47d2-8d72-656a0660f991", component="main-service")
result = app.execute("hostname && hostname -i")
```

We connected successfully and began our investigation.

---

## Phase 3: Testing DNS Resolution (The Dead End)

Our first hypothesis: Maybe App Platform provides DNS names for individual replicas, similar to Kubernetes StatefulSets.

**What we tried:**

1. **Service DNS**: `nslookup main-service` → **Worked!** Returned a single ClusterIP (round-robin load balancer)

2. **StatefulSet-style DNS**: `nslookup main-service-0`, `main-service-1`, `main-service-2` → **Failed.** No DNS records.

3. **Pod name DNS**: `nslookup main-service-768976868d-gtxdh` → **Failed.** No DNS records.

4. **Checked /etc/hosts**: Only the current pod's hostname was mapped to its IP. No entries for peers.

**Conclusion**: App Platform doesn't provide individual DNS names for replicas. The service DNS only returns a single load-balanced IP, not the individual pod IPs.

---

## Phase 4: The Realization

This behavior made sense once we understood the underlying architecture:

**App Platform uses Kubernetes Deployments, not StatefulSets.**

| Feature | StatefulSet | Deployment (App Platform) |
|---------|-------------|---------------------------|
| Pod identity | Stable (`pod-0`, `pod-1`) | Ephemeral (random suffix) |
| DNS | Headless service with per-pod DNS | Single ClusterIP, no per-pod DNS |
| Storage | Persistent volumes per pod | No persistent volumes |
| Use case | Stateful apps (databases, clusters) | Stateless apps (web servers, APIs) |

This is by design. App Platform treats containers as interchangeable "cattle"—perfect for stateless workloads, but problematic for stateful clustered services.

---

## Phase 5: The Brute Force Approach

Since DNS-based discovery wasn't available, we tried a more direct approach: **subnet scanning**.

Each pod knows its own IP address. All pods in the same App Platform app share a network where they can communicate via private IPs. What if we scanned the subnet for other pods listening on our service port?

```python
def discover_peers(port=8080):
    my_ip = socket.gethostbyname(socket.gethostname())
    # Extract base subnet (e.g., "10.244" from "10.244.12.203")
    base = ".".join(my_ip.split(".")[:2])

    # Scan for other hosts listening on our port
    for third in range(0, 50):
        for fourth in range(1, 255):
            ip = f"{base}.{third}.{fourth}"
            # Try to connect...
```

**First attempt**: We scanned only ±10 subnets from our own. Found only 1 replica.

**The problem**: App Platform pods can be scheduled on different nodes with very different subnet addresses. Our three pods were on subnets 0, 6, and 33—far more than ±10 apart.

**Fix**: Expanded the scan to the first 50 `/24` subnets. All three replicas discovered!

**But there's a catch**: This approach finds ALL services listening on port 8080 in the same app—not just replicas of our specific service. If you have a web service, API service, and worker service all on port 8080, they'll all be discovered.

---

## Phase 6: Checking the DO API

We wondered if the DigitalOcean API could provide the instance IPs directly, avoiding the subnet scan.

**What we found:**

```bash
doctl apps list-instances $APP_ID main-service --format Name,Alias
```

Returns:
```
Name                                  Alias
main-service-768976868d-gtxdh        main-service-0
main-service-768976868d-rq7kk        main-service-1
main-service-768976868d-vprdj        main-service-2
```

The API provides instance names and aliases, but **NOT private IPs**. And those aliases (`main-service-0`, etc.) don't resolve via DNS inside the containers.

**Dead end.** The DO API knows about the instances but doesn't expose their network addresses.

---

## Phase 7: Industry Research

At this point, we stepped back and researched how production stateful applications handle this problem.

**Key insight**: If the infrastructure won't help with peer discovery, it must happen at the **application level**.

### Pattern 1: Keycloak's JDBC_PING

Keycloak uses JGroups for clustering. The `JDBC_PING` discovery mechanism works like this:
1. On startup, each replica writes its IP to a `JGROUPSPING` table in a shared database
2. Replicas query this table to find peers
3. Direct TCP connections are established for cluster communication

This works perfectly on App Platform because the database is the discovery mechanism—no special DNS or API needed.

### Pattern 2: Vault's PostgreSQL Backend

Vault's Raft consensus requires stable network identities—exactly what App Platform doesn't provide. The production solution: **eliminate peer discovery entirely**.

By using PostgreSQL as the storage backend (instead of Raft), Vault becomes stateless. The database handles locking and HA. Replicas don't need to find each other because they all talk to the database.

### Pattern 3: Central Registry

For custom applications, implement a database-backed registry:
1. On startup, register `(service_name, instance_id, private_ip)` in a shared table
2. Query the registry to discover peers
3. Use TTL-based expiration for stale entries

---

## Phase 8: Attempting to Update the Running App

We wanted to show our findings in a live demo app. Our first attempt was to modify the code directly in the running containers using the SDK.

**The problem**: When we sent `SIGHUP` to reload the application, it restarted the container—losing our changes since the container uses the original image.

**Alternative attempt**: Deploy with inline Python code in the `run_command`. This failed due to complex escaping issues with heredocs and YAML.

**Final solution**: Create a proper GitHub repository with the demo code and deploy from source. App Platform's buildpack handled the Python deployment automatically.

---

## Conclusions

### The "90% Rule"

For most use cases on serverless container platforms: **Don't cluster the containers; cluster the data.**

Move state to managed databases (PostgreSQL, Redis) and keep containers stateless. This sidesteps the entire peer discovery problem.

### When You Must Have Peer Discovery

If your application requires direct peer-to-peer communication:

1. **Use built-in mechanisms** if available (JDBC_PING for Keycloak, Gossip protocols with database seeds)

2. **Implement a central registry** using your existing database—each replica registers its IP and queries for peers

3. **Subnet scanning** works but is a last resort—it's imprecise and discovers all services on the same port

### Platform Comparison

| Platform | Model | Peer Discovery |
|----------|-------|----------------|
| Kubernetes StatefulSet | Pets (stable identity) | DNS-based (`pod-0.svc`) |
| App Platform / Fargate / Cloud Run | Cattle (ephemeral) | Application-level required |

### What We Verified

| Discovery Method | Works? | Notes |
|------------------|--------|-------|
| Service DNS (`main-service`) | Yes | Returns single ClusterIP (round-robin) |
| Individual pod DNS (`main-service-0`) | No | Not a headless service |
| `doctl apps list-instances` | Partial | Returns names, NOT private IPs |
| Subnet scanning | Yes | Finds all services on the port |
| Direct IP communication | Yes | Once IPs are known, replicas can talk |

---

## The Journey Summary

1. **Started with curiosity**: Can App Platform replicas communicate?
2. **Connected to containers** using the DO App Sandbox SDK
3. **Hit a wall with DNS**: No individual replica DNS names available
4. **Understood why**: App Platform uses Deployments, not StatefulSets
5. **Tried brute force**: Subnet scanning worked but with limitations
6. **Checked the API**: Instance names available, but not IPs
7. **Researched industry patterns**: Found JDBC_PING and database-backed approaches
8. **Reached the conclusion**: Write state to shared storage; let all replicas read from it

The final recommendation: **If your stateful application can offload state to a managed database, do that. If it can't, implement application-level peer discovery using a central registry.**

---

## Live Demo

**URL**: https://replica-comm-demo-ty4kj.ondigitalocean.app

**Repository**: https://github.com/bikramkgupta/demo-replica-communication-app-platform

Refresh the page multiple times to see different hostnames as the load balancer rotates between replicas. Each replica discovers its peers via subnet scanning and displays the cluster status.
