rule summarize_files:
    output:
        summary=config["outputs"]["summary"],
    conda:
        "../envs/base.yaml"
    script:
        "../scripts/generate_outputs.py"
