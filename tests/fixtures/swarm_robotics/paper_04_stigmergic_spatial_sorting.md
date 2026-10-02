# Stigmergic Coordination for Swarm Cluster Formation without Direct Messaging

Authors: Amina Diop, Lucas Moreau
Year: 2023
Venue: Swarm Intelligence
DOI: 10.1007/s11721-023-00214-7
ArXiv: 2311.08210

## Abstract
Direct wireless communication between agents introduces scalability bottlenecks, spectrum congestion, and RF interception risks. Biological insect swarms frequently coordinate through stigmergy—indirect environmental modification—eliminating message broadcasting entirely. We implement an artificial pheromone deposition controller for robotic cluster formation using localized floor markers. Experiments with N=40 Kilobot physical robots confirm that stigmergic coordination scales independently of swarm size. However, convergence time is approximately 4.5 times slower than active RF communication, establishing an empirical trade-off between communication overhead and task execution latency.

## 1. Introduction
In hostile or radio-jammed settings, direct inter-robot communication is either unavailable or hazardous. Stigmergic systems utilize virtual or physical traces left in the environment (e.g., RFID tags, chemical trails, or digital overhead projected pheromones) to guide subsequent actions.

## 2. Pheromone Deposition Model
The environmental concentration field $C(x, y, t)$ evolves according to diffusion and evaporation:
$$\frac{\partial C}{\partial t} = D \nabla^2 C - \mu C + \sum_{i} q_i \delta(x - x_i, y - y_i)$$
where $D$ is the diffusion constant, $\mu$ is the evaporation rate, and $q_i$ is the deposit rate of robot $i$.

- algorithm: Stigmergic Gradient Descent Aggregation (SGDA)

## 3. Physical & Simulated Experiments
Evaluated on physical Kilobot hardware (N=40) and custom 2D Python simulation (N=100).
- finding: Eliminating direct RF messaging guarantees zero packet drop vulnerabilities and zero bandwidth overhead.
- finding: Cluster formation order parameter reaches 0.94 asymptotically without any neighbor tracking.
- result: Aggregation time averaged 245.0 seconds for N=40 Kilobots, compared to 55.0 seconds for radio-based potential field methods.

## 4. Limitations
- limitation: Convergence latency is substantially slower than active RF messaging protocols, rendering pure stigmergy unsuitable for time-critical multi-robot maneuvers.
- limitation: Requires specialized hardware or smart substrate environments to detect and deposit environmental markers.
