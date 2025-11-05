# https://github.com/serv0id/skipera
import sys
import click
import requests
import config
from loguru import logger
from assessment.solver import GradedSolver


class Skipera(object):
    def __init__(self, course: str, llm: bool, solve_assignments: bool):
        self.user_id = None
        self.course_id = None
        self.base_url = config.BASE_URL
        self.session = requests.Session()
        self.session.headers.update(config.HEADERS)
        self.session.cookies.update(config.COOKIES)
        self.course = course
        self.llm = llm
        self.solve_assignments = solve_assignments
        if not self.get_userid():
            self.login()  # implementation pending

    def login(self):
        logger.debug("Trying to log in using credentials")
        r = self.session.post(self.base_url + "login/v3", json={
            "code": "",
            "email": config.EMAIL,
            "password": config.PASSWORD,
            "webrequest": True,
        })

        logger.info(r.content)

    def get_userid(self):
        r = self.session.get(self.base_url + "adminUserPermissions.v1?q=my").json()
        try:
            self.user_id = r["elements"][0]["id"]
            logger.info("User ID: " + self.user_id)
        except KeyError:
            if r.get("errorCode"):
                logger.error("Error Encountered: " + r["errorCode"])
            return False
        return True

    # hierarchy - Modules > Lessons > Items
    def get_modules(self):
        r = self.session.get(self.base_url
                             + f"onDemandCourseMaterials.v2/?q=slug&slug={self.course}&includes=modules").json()
        self.course_id = r["elements"][0]["id"]
        logger.debug("Course ID: " + self.course_id)
        logger.debug("Number of Modules: " + str(len(r["linked"]["onDemandCourseMaterialModules.v1"])))
        for x in r["linked"]["onDemandCourseMaterialModules.v1"]:
            logger.info(x["name"] + " -- " + x["id"])

    def get_items(self):
        r = self.session.get(self.base_url + "onDemandCourseMaterials.v2/", params={
            "q": "slug",
            "slug": self.course,
            "includes": "passableItemGroups,passableItemGroupChoices,items,tracks,gradePolicy,gradingParameters",
            "fields": "onDemandCourseMaterialItems.v2(name,slug,timeCommitment,trackId)",
            "showLockedItems": "true"
        }).json()
        for video in r["linked"]["onDemandCourseMaterialItems.v2"]:
            logger.info("Watching " + video["name"])
            self.watch_item(video["id"], video.get("timeCommitment"))

    def watch_item(self, item_id, time_commitment):
        r = self.session.post(
            self.base_url + f"opencourse.v1/user/{self.user_id}/course/{self.course}/item/{item_id}/lecture"
                            f"/videoEvents/ended?autoEnroll=false",
            json={"contentRequestBody": {}}).json()
        if r.get("contentResponseBody") is None:
            logger.info("Not a watch item! Reading..")
            self.read_item(item_id)
        elif time_commitment:
            self.mark_video_completed(item_id, time_commitment)

    def mark_video_completed(self, item_id, time_commitment):
        video_progress_id = f"{self.user_id}~{self.course_id}~{item_id}"
        duration_ms = time_commitment * 1000
        url = self.base_url + f"onDemandVideoProgresses.v1/{video_progress_id}"
        payload = {
            "viewedUpTo": duration_ms,
            "videoProgressId": video_progress_id
        }
        r = self.session.put(url, json=payload)
        if r.status_code in [200, 204]:
            logger.info("Video marked as completed.")
        else:
            logger.error(f"Failed to mark video as completed. Status: {r.status_code}, Response: {r.text}")

    def read_item(self, item_id):
        r = self.session.post(self.base_url + "onDemandSupplementCompletions.v1", json={
            "courseId": self.course_id,
            "itemId": item_id,
            "userId": int(self.user_id)
        })
        if "Completed" not in r.text:
            logger.debug("Item is a quiz/assignment!")
            if self.solve_assignments and "StaffGradedContent" in r.text and self.llm:
                logger.debug("Attempting to solve graded assessment..")
                solver = GradedSolver(self.session, self.course_id, item_id)
                solver.solve()


@click.command()
@click.option('--slug', required=True, help="The course slug from the URL")
@click.option('--llm', is_flag=True, help="Whether to use an LLM to solve graded assignments.")
@click.option('--dont-solve-assignments', is_flag=True, help="Do not attempt to solve assignments.")
@click.option('-v', '--verbose', count=True, help="Increase verbosity (e.g., -v, -vv).")
def main(slug: str, llm: bool, dont_solve_assignments: bool, verbose: int) -> None:
    logger.remove()
    if verbose == 0:
        logger.add(sys.stderr, level="INFO")
    elif verbose == 1:
        logger.add(sys.stderr, level="DEBUG")
    else:
        logger.add(sys.stderr, level="TRACE")

    try:
        skipera = Skipera(slug, llm, not dont_solve_assignments)
        skipera.get_modules()
        skipera.get_items()
    except Exception as e:
        logger.exception(e)


if __name__ == '__main__':
    main()
