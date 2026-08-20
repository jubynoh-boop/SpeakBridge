# Security policy

## Supported versions

SpeakBridge is currently alpha software. Security fixes are made on the latest release only.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability or include private meeting transcripts in an issue.

Until a dedicated security email is published, use GitHub's **Report a vulnerability** private advisory feature on the repository's Security tab. Include the affected version, reproduction steps, expected impact, and logs with personal data and transcripts removed.

The maintainer will acknowledge a complete report when available, investigate it, and coordinate disclosure after a fix. This policy does not promise a specific response deadline while the project is maintained by volunteers.

## Local service boundary

SpeakBridge binds its web and API services to loopback interfaces. Do not modify launch scripts to bind to a LAN/public address without adding authentication, request-size limits, and an explicit threat review.
