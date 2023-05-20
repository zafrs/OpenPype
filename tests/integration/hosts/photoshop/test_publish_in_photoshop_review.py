import logging

from tests.lib.assert_classes import DBAssert
from tests.integration.hosts.photoshop.lib import PhotoshopTestClass

log = logging.getLogger("test_publish_in_photoshop")


class TestPublishInPhotoshopImageReviews(PhotoshopTestClass):
    """Test for publish in Phohoshop with different review configuration.

    Workfile contains 2 image instance, one has review flag, second doesn't.

    Regular `review` family is disabled.

    Expected result is to `imageMainForeground` to have additional file with
    review, `imageMainBackground` without. No separate `review` family.

    `test_project_test_asset_imageMainForeground_v001_jpg.jpg` is expected name
    of imageForeground review, `_jpg` suffix is needed to differentiate between
    image and review file.

    """
    PERSIST = True

    TEST_FILES = [
        ("12WGbNy9RJ3m9jlnk0Ib9-IZmONoxIz_p",
         "test_photoshop_publish_review.zip", "")
    ]

    APP_GROUP = "photoshop"
    # keep empty to locate latest installed variant or explicit
    APP_VARIANT = ""

    APP_NAME = "{}/{}".format(APP_GROUP, APP_VARIANT)

    TIMEOUT = 120  # publish timeout

    def test_db_asserts(self, dbcon, publish_finished):
        """Host and input data dependent expected results in DB."""
        print("test_db_asserts")
        failures = []

        failures.append(DBAssert.count_of_types(dbcon, "version", 3))

        failures.append(
            DBAssert.count_of_types(dbcon, "version", 0, name={"$ne": 1}))

        failures.append(
            DBAssert.count_of_types(dbcon, "subset", 1,
                                    name="imageMainForeground"))

        failures.append(
            DBAssert.count_of_types(dbcon, "subset", 1,
                                    name="imageMainBackground"))

        failures.append(
            DBAssert.count_of_types(dbcon, "subset", 1,
                                    name="workfileTest_task"))

        failures.append(
            DBAssert.count_of_types(dbcon, "representation", 6))

        additional_args = {"context.subset": "imageMainForeground",
                           "context.ext": "png"}
        failures.append(
            DBAssert.count_of_types(dbcon, "representation", 1,
                                    additional_args=additional_args))

        additional_args = {"context.subset": "imageMainForeground",
                           "context.ext": "jpg"}
        failures.append(
            DBAssert.count_of_types(dbcon, "representation", 2,
                                    additional_args=additional_args))

        additional_args = {"context.subset": "imageMainForeground",
                           "context.ext": "jpg",
                           "context.representation": "jpg_jpg"}
        failures.append(
            DBAssert.count_of_types(dbcon, "representation", 1,
                                    additional_args=additional_args))

        additional_args = {"context.subset": "imageMainBackground",
                           "context.ext": "png"}
        failures.append(
            DBAssert.count_of_types(dbcon, "representation", 1,
                                    additional_args=additional_args))

        additional_args = {"context.subset": "imageMainBackground",
                           "context.ext": "jpg"}
        failures.append(
            DBAssert.count_of_types(dbcon, "representation", 1,
                                    additional_args=additional_args))

        additional_args = {"context.subset": "imageMainBackground",
                           "context.ext": "jpg",
                           "context.representation": "jpg_jpg"}
        failures.append(
            DBAssert.count_of_types(dbcon, "representation", 0,
                                    additional_args=additional_args))

        additional_args = {"context.subset": "review"}
        failures.append(
            DBAssert.count_of_types(dbcon, "representation", 0,
                                    additional_args=additional_args))

        assert not any(failures)


if __name__ == "__main__":
    test_case = TestPublishInPhotoshopImageReviews()
