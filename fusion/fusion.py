import warnings
warnings.filterwarnings('ignore')

from fusion_admin import fusion_admin_present, fusion_admin_future
from fusion_user  import fusion_user

if __name__ == "__main__":

    print("\n" + "="*55)
    print("FUSION 1 — Admin Present (Temple, Camera K)")
    print("="*55)
    f1 = fusion_admin_present(
        location_name  = "Siddhivinayak Temple",
        yolo_count     = 85,
        gnn_flow_score = 0.75,
        cctv_id        = 11
    )
    for k, v in f1.items():
        print(f"  {k:25s}: {v}")

    print("\n" + "="*55)
    print("FUSION 2 — Admin Future (Temple, 1hr ahead)")
    print("="*55)
    f2 = fusion_admin_future(
        fusion1_result = f1,
        location_name  = "Siddhivinayak Temple",
        hours_ahead    = 1
    )
    for k, v in f2.items():
        print(f"  {k:25s}: {v}")

    print("\n" + "="*55)
    print("FUSION 3 — User (Andheri → Juhu Beach)")
    print("="*55)
    f3 = fusion_user(
        user_location = "Andheri",
        destination   = "Juhu Beach"
    )
    for k, v in f3.items():
        print(f"  {k:25s}: {v}")