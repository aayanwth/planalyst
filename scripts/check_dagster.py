from planalyst.dagster_assets.definitions import defs

job_mw = defs.get_job_def("matchweek_pipeline")
job_train = defs.get_job_def("model_training_job")
print("matchweek_pipeline loaded")
print("model_training_job loaded")
print("asset keys:")
for k in sorted(str(x) for x in defs.get_repository_def().asset_graph.get_all_asset_keys()):
    print(" ", k)
