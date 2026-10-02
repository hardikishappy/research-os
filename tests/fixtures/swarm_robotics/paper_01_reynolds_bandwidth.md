# Scalable Decentralized Flocking under Strict Bandwidth Limits

Authors: Marcus Vance, Elena Rostova
Year: 2023
Venue: IEEE Transactions on Robotics
DOI: 10.1109/TRO.2023.1092831
ArXiv: 2304.09182

## Abstract
Decentralized robotic swarms operating in radio-degraded environments encounter severe communication bottlenecks as the number of agents scales. Traditional flocking algorithms assume periodic high-frequency broadcast of position and velocity vectors. We present a bandwidth-constrained flocking protocol that compresses state exchanges into 16-bit quantizations. Evaluated across swarm sizes ranging from N=20 to N=100 in the ARGoS simulator, our method maintains cohesive polarization while reducing channel congestion by 65%. However, when packet drop rates exceed 15%, velocity consensus degrades sharply, revealing an unaddressed vulnerability in asynchronous swarm coordination.

## 1. Introduction
Coordinated collective motion in autonomous multi-agent systems relies on rapid alignment of velocities among spatial neighbors. In real-world field robotics, such as subterranean exploration and oceanic monitoring, radio channels are strictly shared and subject to packet collisions and packet drop. When hundreds of robots attempt to broadcast state vectors simultaneously at 10 Hz, the wireless medium rapidly saturates, causing message delays that destabilize flock cohesion.

## 2. Related Work
Classical approaches derive from Reynolds Boids and Olfati-Saber's consensus protocols. While Olfati-Saber established Lyapunov stability for alpha-lattices under idealized communication graphs, empirical performance under packet drop remains poorly bounded. Vicsek models similarly presume instantaneous angular alignment.

## 3. Methodology & Force Formulation
We define the inter-agent interaction force $F_{ij}$ between robot $i$ and neighbor $j$ using an artificial physics potential:
$$F_{ij} = -\nabla V(r_{ij}) = -\left( \frac{a}{r_{ij}^2} - \frac{b}{r_{ij}} \right) \hat{r}_{ij}$$
where $r_{ij} = ||p_j - p_i||$ is the Euclidean distance and $\hat{r}_{ij}$ is the unit orientation vector. To reduce bandwidth, velocity vectors are quantized into 8-sector discrete compass bins before transmission.

- algorithm: Quantized State Consensus Protocol (QSCP)
- algorithm: Periodic 10Hz Compressed Broadcast

## 4. Experimental Setup
Simulations were executed within the ARGoS multi-robot simulator across swarm sizes of N=20, 50, and 100 agents. The arena size was 20m x 20m with periodic boundary conditions. Robots operated with a simulated radio range of $r = 2.5$ meters. Bandwidth caps were enforced at 128 bytes/second per robot.

## 5. Results & Key Findings
- finding: Quantized velocity vectors preserve flock polarization within 6% of continuous floating-point exchange up to N=100 agents.
- finding: Total communication load dropped from 840 bytes/sec to 112 bytes/sec per agent.
- result: Swarm aggregation time averaged 42.4 seconds for N=50 under ideal packet delivery.

## 6. Limitations & Unresolved Challenges
- limitation: Flocking polarization collapses when asynchronous packet drop rate exceeds 15%, causing fragmentation into uncoordinated sub-swarms.
- limitation: The protocol was evaluated only up to N=100 agents; scaling behavior for ultra-dense swarms (N >= 200) under bandwidth caps remains completely unexamined.
- constraint: Assumes local relative positioning is noise-free.
