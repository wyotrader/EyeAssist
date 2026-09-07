# External model source provenance

EyeAssist's live project contained clean local checkouts of the following model
research repositories. They are external upstream projects, not maintained
EyeAssist application source, so their complete checkouts and nested Git
metadata are intentionally not vendored into this baseline. Model weights and
checkpoints are also excluded. These references record the integration sources
that were present during migration.

| Integration | Upstream repository | Observed commit |
| --- | --- | --- |
| Corneal disease | https://github.com/amirrdr/keratitis-detection-slitlamp.git | `77929f9996ab87d89ee8147e30b89143c8159fb4` |
| FairCLIP | https://github.com/Harvard-Ophthalmology-AI-Lab/FairCLIP.git | `caedce4c8aecfcd5f198194b0e31a972d9bd3da3` |
| FairSeg | https://github.com/Harvard-Ophthalmology-AI-Lab/FairSeg.git | `7ebec8db630b87937d446eb2f072e15ee0720f23` |
| Harvard-GDP | https://github.com/Harvard-Ophthalmology-AI-Lab/Harvard-GDP.git | `731527ef88be880ee1a650cedd0a8072dfd10ff8` |
| CAMG segmentation | https://github.com/ljw-fzu/AI_for_CAMG.git | `4ba3c23bf18ade952d0e712e15dd81464e6794f1` |
| RETFound | https://github.com/rmaphoh/RETFound_MAE.git | `ae9a9ecf37857cf47b8aa9f87cd6f710d75db287` |
| RNFLT2Vec | https://github.com/Harvard-Ophthalmology-AI-Lab/RNFLT2Vec.git | `8c789220b88785765639aed96141e6cd33c6a6c3` |
| VFTransformer | https://github.com/Harvard-Ophthalmology-AI-Lab/VFTransformer.git | `f250df18278a1870f25f7f92433eb3320fe3bf78` |

Fetch, licensing review, and deployment of these external integrations should
remain explicit deployment steps rather than additions of generated model or
runtime payloads to this repository.
