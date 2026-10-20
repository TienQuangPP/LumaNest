# Third-party models and libraries

Additional local tools (2026-10-15): [Meta SAM 2.1 Hiera Tiny](https://huggingface.co/facebook/sam2.1-hiera-tiny), Apache-2.0, pinned `de431c4043854a71d8101e17995dfe596bf101a5`; safetensors only, Transformers image inference. [Qwen3-1.7B GGUF](https://huggingface.co/Qwen/Qwen3-1.7B-GGUF), Apache-2.0, pinned `90862c4b9d2787eaed51d12237eafdfe7c5f6077`, Q8_0 checkpoint. [llama.cpp](https://github.com/ggml-org/llama.cpp), MIT, official Windows CPU release `b11669`; upstream ZIP SHA-256 `37b3efcf962847ca869745fd4ccf7f5e7e8dacfeff9fa3523b4ca8cdc66d632b`. The fetch scripts verify upstream checksums and write provenance manifests. Runtime/model files are excluded from the source ZIP. Local chat sends text only to its authenticated loopback worker; no tools and no access to photos. Retain upstream license notices when redistributing those assets.

The application downloads upstream material; model files are excluded from the source distribution. Preserve the upstream license files saved alongside each model. Source code licenses do not automatically establish unrestricted rights to pretrained weights or their training data.

| Asset | Upstream | Notes |
|---|---|---|
| MTCNN and optional InceptionResnetV1 | https://github.com/timesler/facenet-pytorch | Upstream source snapshot, `LICENSE.md` downloaded alongside it; pretrained detection weights included upstream |
| AdaFace IR50 backbone and weights | https://huggingface.co/minchul/cvlface_adaface_ir50_webface4m | Author-published CVLFace checkpoint; fixed revision; model card directs users to respect training-dataset conditions |
| CVLFace source license | https://github.com/mk-minchul/CVLface | MIT source license downloaded to weights/adaface/LICENSE |
| Fast Neural Style | https://github.com/pytorch/examples/tree/main/fast_neural_style | Upstream architecture and pretrained preset archive; source license downloaded alongside architecture |
| VGG19 | https://docs.pytorch.org/vision/stable/models/generated/torchvision.models.vgg19.html | Torchvision architecture; ImageNet pretrained checkpoint hosted by PyTorch |
| OpenVINO CPU runtime | https://github.com/openvinotoolkit/openvino | Optional PyPI dependency, Apache-2.0; compiled IR/cache derived locally from original preset weights, excluded from source ZIP |
| Google SigLIP 2 Base | https://huggingface.co/google/siglip2-base-patch16-224 | Model card Apache-2.0. Revision 75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2. Local safetensors; manifest in weights/siglip2/provenance.json. Weights excluded from source ZIP |
| Hugging Face Transformers | https://github.com/huggingface/transformers | Apache-2.0; installed from PyPI, optional requirements-semantic.txt; no remote modeling Python executed |
| Van Gogh reference | https://collectionapi.metmuseum.org/public/collection/v1/objects/436535 | Wheat Field with Cypresses, Vincent van Gogh, public domain per The Met API. Downloaded from The Met; pinned SHA-256 and attribution in fsmart/artworks.py and weights/artworks/provenance.json. No pretrained Van Gogh model is claimed |

Optional Gemini API uses Google's native generateContent endpoint; see [official model catalog](https://ai.google.dev/gemini-api/docs/models) and [API key guidance](https://ai.google.dev/gemini-api/docs/api-key). Credentials belong to the user and are held in server RAM; model/API usage follows the provider's applicable terms and quotas. Google receives text only; reference images can be returned after an explicit creation action. No personal source photos are uploaded by this integration.

`weights/provenance.json` records the exact source URLs, Git revisions in URLs, file sizes and SHA-256 hashes used in the local run.

