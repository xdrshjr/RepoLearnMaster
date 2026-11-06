import { redirect } from 'next/navigation';

/** `/course/{id}` has no page of its own: the first layer is the landing layer. */
export default async function CourseIndexPage({
  params,
}: {
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = await params;
  redirect(`/course/${encodeURIComponent(courseId)}/overview`);
}
