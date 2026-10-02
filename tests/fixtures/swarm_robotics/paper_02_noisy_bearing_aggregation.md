# Robust Swarm Aggregation in the Presence of Gaussian Bearing Noise

Authors: Kenji Sato, Priya Nair
Year: 2024
Venue: Autonomous Robots
DOI: 10.1007/s10514-024-09871-3
ArXiv: 2402.11894

## Abstract
Autonomous swarm aggregation frequently assumes clean relative bearing measurements between neighboring agents. Under low-cost infrared and visual sensing, orientation measurements are corrupted by significant angular noise. This paper investigates decentralized attraction-repulsion controllers under zero-mean Gaussian bearing noise with variance up to 20 degrees. Testing across swarms of N=50 agents in the Stage simulator, we demonstrate that angular estimation filtering prevents centroid oscillation. However, when wireless communication drops below 5 Hz, inter-robot collision frequency increases by 300%, demonstrating a severe dependency on communication frequency.

## 1. Introduction
Aggregation is a prerequisite behavior for collective multi-robot exploration, shelter seeking, and cooperative transport. While asymptotic stability has been demonstrated under exact sensory perception, real miniature robots (e.g. e-pucks, Thymio, Kilobots) experience substantial bearing estimation noise caused by photodiode calibration error and surface reflections.

## 2. Sensor Noise & Motion Model
Let robot $i$ observe neighbor $j$ at true relative bearing $\theta_{ij}$. The measured bearing $\tilde{\theta}_{ij}$ is modeled as:
$$\tilde{\theta}_{ij} = \theta_{ij} + \mathcal{N}(0, \sigma_\theta^2)$$
where $\sigma_\theta$ ranges from 5 to 20 degrees. The kinematic update combines artificial potential field repulsion with noise-filtered bearing vectors.

- algorithm: Noise-Filtered Attraction-Repulsion Controller (NF-ARC)

## 3. Simulation & Empirical Setup
Simulations were performed using Stage simulator in a bounded 15m x 15m arena containing N=50 mobile robots with maximum speed $v_{max} = 0.2$ m/s. Sensing range was limited to $r = 3.0$ m.

## 4. Key Findings
- finding: An exponential moving average bearing filter stabilizes cluster centroid drift under Gaussian noise $\sigma_\theta = 15^\circ$.
- finding: Swarm order parameter reached 0.88 within 60 seconds under 10 Hz messaging rate.
- result: Swarm aggregation time averaged 54.2 seconds across 30 Monte Carlo trials.

## 5. Limitations
- limitation: Lowering communication frequency below 5 Hz causes a 300% spike in collision frequency, as robots cannot predict neighbor trajectories in time to avoid dynamic contact.
- limitation: Evaluated strictly at N=50; behavior under combined noise and bandwidth starvation at N >= 200 is unverified.
- constraint: Obstacle-rich environments were not evaluated.
