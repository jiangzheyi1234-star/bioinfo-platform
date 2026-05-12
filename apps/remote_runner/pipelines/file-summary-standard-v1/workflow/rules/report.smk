rule render_report:
    input:
        summary=config["outputs"]["summary"],
    output:
        report=config["outputs"]["report"],
        raw_log=config["outputs"]["raw_log"],
    conda:
        "../envs/base.yaml"
    script:
        "../scripts/generate_outputs.py"
