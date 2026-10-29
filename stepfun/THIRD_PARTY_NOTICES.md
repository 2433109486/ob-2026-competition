# Third-Party Notices

SeekBase includes or depends on the following open-source projects. The model
weights are third-party artifacts; they are not authored by this project.

| Component | Version / revision | License | Source |
|---|---|---|---|
| BAAI/bge-small-zh-v1.5 | base model | MIT | https://huggingface.co/BAAI/bge-small-zh-v1.5 |
| Xenova/bge-small-zh-v1.5 (ONNX) | `75c43b069aac4d136ba6bc1122f995fedcfd2781` | MIT (base model) | https://huggingface.co/Xenova/bge-small-zh-v1.5 |
| Transformers.js (`@huggingface/transformers`) | 3.7.5 | Apache-2.0 | https://github.com/huggingface/transformers.js |
| ONNX Runtime Web | 1.22.0-dev | MIT | https://github.com/microsoft/onnxruntime |
| seekdb | 1.4.0.0 | Apache-2.0 | https://github.com/oceanbase/seekdb |
| seekdb-js (`seekdb`) | 1.4.0 | Apache-2.0 | https://github.com/oceanbase/seekdb-js |
| Express | 5.1.0 | MIT | https://github.com/expressjs/express |
| Playwright (dev only) | 1.55 | Apache-2.0 | https://github.com/microsoft/playwright |

The INT8/fp16 ONNX files are the pre-quantized/float16-converted artifacts
published in the Xenova model repository. Their sizes and SHA-256 hashes are
recorded in `web/models/manifest.json`. The application does not redistribute
any proprietary or gated model.

License texts for the JavaScript dependencies are available in their respective
`node_modules/*/LICENSE` files after `npm install`, and in the upstream
repositories linked above.
