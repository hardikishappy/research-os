# Event-Triggered Inter-Robot Communication for Massive Robot Swarms

Authors: David K. Chen, Sarah Lindqvist
Year: 2024
Venue: Robotics and Autonomous Systems
DOI: 10.1016/j.robot.2024.104612
ArXiv: 2406.04189

## Abstract
Continuous periodic messaging is unsustainable for massive robot swarms scaling to hundreds of agents. We introduce an event-triggered consensus protocol where agents transmit kinematic state only when local velocity change exceeds a dynamic threshold. In simulations of up to N=500 robots in the ARGoS simulator, event-triggered communication cuts wireless packet transmission by 72% while preserving collective trajectory alignment. Nonetheless, the mechanism exhibits stability degradation during abrupt environmental perturbations, indicating an unresolved sensitivity in threshold adaptation.

## 1. Introduction
Massive robotic swarms (N >= 200) deployed in environmental monitoring or search-and-rescue saturate local RF spectra if every robot broadcasts at periodic clock ticks. Event-triggered control offers a principled paradigm where channel access is requested only when significant state innovations occur.

## 2. Event-Triggered Formulation
A broadcast event for agent $i$ is generated at time $t_k$ when the Lyapunov-derived state error exceeds a threshold:
$$||x_i(t) - x_i(t_k)|| \ge \delta_i(t) = \gamma \cdot \exp(-\alpha t) + \epsilon_0$$
where $\delta_i(t)$ is the event threshold, $\gamma$ is a decay coefficient, and $\epsilon_0$ is the steady-state tolerance.

- algorithm: Dynamic Threshold Event-Triggered Consensus (D-ETC)
- algorithm: Asynchronous Neighbor State Predictor

## 3. Simulation & Results
Evaluated in ARGoS simulator with swarms of N=100, 200, and 500 agents. Communication range was set to $r = 2.0$ meters.
- finding: Network packet volume was reduced by 72.4% compared to standard 10 Hz periodic broadcast.
- finding: Flocking order parameter remained above 0.91 during steady-state straight-line cruising.
- result: Swarm collision frequency was negligible during steady cruise in obstacle-free arenas.

## 4. Limitations & Open Challenges
- limitation: During sudden obstacle encounters or boundary reflections, abrupt state divergence leads to simultaneous burst broadcasts across all agents, causing severe channel contention and localized deadlocks.
- limitation: The protocol was evaluated exclusively under ideal noiseless sensors; performance under local bearing and distance sensing noise was not analyzed.
- constraint: Fixed communication range assumption (disk graph).
