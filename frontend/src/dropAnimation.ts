import type { DropAnimation } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import { dndDebug, dndDebugWarn } from "./placementDndDebug";

/** Animerar drag-overlay till droppable-rutan (inte tillbaka till källan). */
export function createDropToCellAnimation(
  getDropTargetId: () => string | null,
  duration = 280
): DropAnimation {
  return ({
    active,
    dragOverlay,
    transform,
    droppableContainers,
    measuringConfiguration,
  }) => {
    const overId = getDropTargetId();

    let finalX = transform.x - (dragOverlay.rect.left - active.rect.left);
    let finalY = transform.y - (dragOverlay.rect.top - active.rect.top);
    let targetFound = false;

    if (overId) {
      const container = droppableContainers.get(overId);
      const node = container?.node.current;
      if (node) {
        const overRect = measuringConfiguration.droppable.measure(node);
        finalX = transform.x + (overRect.left - dragOverlay.rect.left);
        finalY = transform.y + (overRect.top - dragOverlay.rect.top);
        targetFound = true;
      }
    }

    dndDebug("dropAnimation", {
      activeId: String(active.id),
      overId,
      targetFound,
      duration,
      from: { x: transform.x, y: transform.y },
      to: { x: finalX, y: finalY },
    });
    if (overId && !targetFound) {
      dndDebugWarn("dropAnimation: overId finns men droppable-nod saknas", { overId });
    }

    const keyframes = [
      { transform: CSS.Transform.toString(transform) },
      {
        transform: CSS.Transform.toString({
          x: finalX,
          y: finalY,
          scaleX: 1,
          scaleY: 1,
        }),
      },
    ];

    const animation = dragOverlay.node.animate(keyframes, {
      duration,
      easing: "ease-out",
      fill: "forwards",
    });

    return new Promise<void>((resolve) => {
      animation.onfinish = () => {
        dndDebug("dropAnimation klar (finish)");
        resolve();
      };
      animation.oncancel = () => {
        dndDebugWarn("dropAnimation avbruten (cancel)");
        resolve();
      };
    });
  };
}
