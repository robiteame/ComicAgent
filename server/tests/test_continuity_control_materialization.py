"""一致性控制图物化与视频参考预检的回归测试。

背景：complex_motion 镜头在前镜尚无末帧（重生成队列、每场首镜）时，一致性画像
仍声明 openpose/depth 锁 enabled 而参考图为空，视频生成预检以
「视频生成缺少必需一致性参考素材: openpose_control:<empty>」直接失败。
物化需回退到已审核分镜首帧；确实无法物化时锁标志必须降级，不允许画像说谎。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SERVER_DIR = Path(__file__).resolve().parents[1]
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

from test_environment import TEST_ROOT  # noqa: F401,E402

from PIL import Image  # noqa: E402

from api.routes import shot as shot_route  # noqa: E402
from config import settings  # noqa: E402
from services.video_service import VideoService  # noqa: E402


def _write_png(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (200, 120, 40)).save(path)
    return str(path)


def _shot_data(storyboard_path: str = "") -> dict:
    return {
        "shot_id": "regenfix_shot_0001",
        "storyboard_path": storyboard_path,
        "image_path": storyboard_path,
        "continuity_reference_path": "",
        "pose_reference_path": "",
        "depth_reference_path": "",
        "reference_weights": {"action": 0.3, "environment": 0.45},
        "reference_assets": [],
        "continuity_profile": {
            "complex_motion": True,
            "openpose_lock": "enabled",
            "depth_lock": "enabled",
            "previous_reference_path": "",  # 前镜尚无末帧
        },
    }


class MaterializeControlReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project_id = "regenfix_project"
        # 参考图必须落在 OUTPUT_DIR 等允许根目录内，物化才会认。
        self.storyboard = _write_png(settings.OUTPUT_DIR / "regenfix" / "proj_shot_0001.png")

    def test_storyboard_fallback_materializes_controls(self) -> None:
        shot_data = _shot_data(self.storyboard)
        shot_route._materialize_control_references(self.project_id, shot_data, None)

        pose = shot_data["pose_reference_path"]
        depth = shot_data["depth_reference_path"]
        self.assertTrue(pose and Path(pose).exists())
        self.assertTrue(depth and Path(depth).exists())
        self.assertEqual(shot_data["continuity_profile"]["openpose_lock"], "enabled")
        self.assertEqual(shot_data["continuity_profile"]["depth_lock"], "enabled")
        asset_types = {asset["type"] for asset in shot_data["reference_assets"]}
        self.assertIn("openpose_source_frame", asset_types)
        self.assertIn("depth_source_frame", asset_types)

    def test_skill_gate_off_downgrades_lock_flags(self) -> None:
        shot_data = _shot_data(self.storyboard)
        skill_config = {"storyboard_agent": {"openpose_lock_enabled": False}}
        shot_route._materialize_control_references(self.project_id, shot_data, skill_config)

        profile = shot_data["continuity_profile"]
        self.assertEqual(profile["openpose_lock"], "not_required")
        self.assertEqual(profile["depth_lock"], "not_required")
        self.assertEqual(shot_data["pose_reference_path"], "")
        self.assertEqual(shot_data["depth_reference_path"], "")

    def test_no_source_downgrades_lock_flags(self) -> None:
        shot_data = _shot_data("")  # 前镜末帧、续帧参考、分镜图全部缺失
        shot_route._materialize_control_references(self.project_id, shot_data, None)

        profile = shot_data["continuity_profile"]
        self.assertEqual(profile["openpose_lock"], "not_required")
        self.assertEqual(profile["depth_lock"], "not_required")


class VideoReferenceValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = VideoService()
        self.project_id = "regenfix_project"
        storyboard = _write_png(settings.OUTPUT_DIR / "regenfix" / "val_shot_0001.png")
        shot_data = _shot_data(storyboard)
        shot_route._materialize_control_references(self.project_id, shot_data, None)
        self.shot = shot_data

    def test_materialized_controls_pass_video_precheck(self) -> None:
        manifest = self.service._validate_video_references(self.shot)
        kinds = {item["type"] for item in manifest}
        self.assertIn("approved_storyboard_first_frame", kinds)
        self.assertIn("openpose_control", kinds)
        self.assertIn("depth_control", kinds)

    def test_enabled_lock_without_controls_still_fails_precheck(self) -> None:
        # 契约：画像声明 enabled 而素材缺失仍必须硬失败——物化降级保证这不再发生。
        lying = _shot_data(self.shot["storyboard_path"])
        with self.assertRaisesRegex(RuntimeError, "openpose_control"):
            self.service._validate_video_references(lying)

    def test_downgraded_profile_passes_without_controls(self) -> None:
        self.shot["continuity_profile"]["openpose_lock"] = "not_required"
        self.shot["continuity_profile"]["depth_lock"] = "not_required"
        self.shot["pose_reference_path"] = ""
        self.shot["depth_reference_path"] = ""
        manifest = self.service._validate_video_references(self.shot)
        kinds = {item["type"] for item in manifest}
        self.assertIn("approved_storyboard_first_frame", kinds)
        self.assertNotIn("openpose_control", kinds)


if __name__ == "__main__":
    unittest.main()
