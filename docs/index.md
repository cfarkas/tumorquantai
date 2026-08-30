# TumorQuantAI

TumorQuantAI converts H&E whole-slide images into reproducible HistoPLUS cell-type outputs with explicit scale, sampling, provenance, and failure auditing.

![TumorQuantAI workflow](assets/tumorquantai-hero.svg)

## Start here

```bash
# Clone TumorQuantAI and enter the repository.
git clone https://github.com/cfarkas/tumorquantai.git
cd tumorquantai

# Install the global command and Docker route.
./tumorquantai install --docker
export PATH="$HOME/.local/bin:$PATH"

# Prepare the fixed public WSI without model inference.
tumorquantai quickstart --no-inference
```

Choose `--singularity`, `--poetry`, or `--conda` instead of `--docker` during installation when that is your intended route. The installer includes the download, conversion, and inspection dependencies, so tutorials do not create another Python environment.

## Guided workflows

- [Install TumorQuantAI](installation.md)
- [Configure HistoPLUS access](how-to/model-access.md)
- [QuickStart Example 1: one public WSI](quick_start.md)
- [Full tutorial: 21 lymphoma WSIs at 10%](full_tutorial.md)
- [Breast ER/PR/HER2/Ki-67 patch quantification](tutorials/breast-ihc-patches.md)
- [Colon CD3/CD8 whole-slide quantification guided by CK20](tutorials/colon-ihc-wsi-immunoscore.md)
- [Apply TumorQuantAI to your own WSIs](own_data.md)
- [Execution methods](execution_environments.md)
- [Understand the outputs](outputs.md)

Public WSI download, checksum validation, conversion, and inspection require no HistoPLUS credential. Inference requires approved access to the gated HistoPLUS model.
