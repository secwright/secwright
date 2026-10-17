# Security policy

## Reporting a vulnerability in Secwright

Please **don't open a public issue** for a security problem in Secwright itself (the agent, the sandbox, the graders or the published weights).

Report it privately through GitHub instead: go to the **Security** tab of this repo and click **Report a vulnerability**. We aim to acknowledge reports within 5 working days and will keep you updated until it's resolved. Tell us if you'd like to be credited.

Examples of in-scope issues:
- a way for code run by the agent to escape its sandbox
- a way to make a grader accept a fix that doesn't work
- tampered or unsafe published artifacts (images, weights, datasets)

## Intended use

Secwright is for **defensive** work on code and infrastructure that you own or are authorised to secure.

- Training environments are built only from **publicly disclosed, already-patched** vulnerabilities, and reward **fixing** them.
- Hidden tests check for **safe behaviour**. The project doesn't ship weaponised exploit payloads.
- The project doesn't build tools for attacking live or third-party systems.

Open model weights can be modified by anyone, so the published model cards will describe the model's limits and the misuse evaluations we ran. If you find the model giving meaningful help with attacking systems, please report it through the private channel above.
